"""Drop-in replacement for the scheduled-job runner using the tmux supervisor.

Use this from APScheduler jobs (or anywhere) instead of spawning `claude`
directly. Each call lazily ensures the agent's tmux session exists, sends the
prompt, and waits for the pane to stabilise.

Workdirs are pane-prefixed (``~/.borina/agents/p<PANE>/<agent_id>``) so the
eight parallel refactor instances do not stomp on each other's per-agent state.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from agents.tmux_supervisor import get_supervisor

def _workdir_root() -> Path:
    """Resolve workdir root at call time so post-import .env loads apply."""
    pn = os.environ.get("BORINA_PANE_NUMBER", "1")
    return Path.home() / ".borina" / "agents" / f"p{pn}"


# ── agent id mapping ──────────────────────────────────────────────────────
# Short ids used in tmux session names + URLs map to the long Agent.id
# ClassVars in agents/*.py. System prompts are read from those classes via
# `agents.base.registry` so editing an agent's system_prompt in one place
# is enough — no hardcoded copies to drift out of sync.

AGENT_REGISTRY: dict[str, dict] = {
    "trader":     {"long_id": "trader"},
    "inbox":      {"long_id": "inbox-triage"},
    "scout":      {"long_id": "ecommerce-scout"},
    "ceo":        {"long_id": "ceo"},
    "polymarket": {"long_id": "polymarket-intel"},
    "researcher": {"long_id": "researcher"},
    "adset":      {"long_id": "adset-optimizer"},
    "planner":    {"long_id": "planner"},
    # Finance gets a fixed workdir (not pane-prefixed) so its CLAUDE.md +
    # BRIEF_FORMAT.md specs travel with the agent rather than per pane.
    "finance":    {
        "long_id": "finance",
        "workdir": str(Path.home() / ".borina" / "agents" / "finance"),
    },
}


def _resolve_system_prompt(short_id: str) -> str:
    """Look up the agent class's system_prompt from agents.base.registry.

    Returns "" if the agent isn't registered (e.g. test harness with stub
    classes) or if the import fails — caller falls back to a generic prompt.
    """
    long_id = AGENT_REGISTRY.get(short_id, {}).get("long_id", short_id)
    try:
        from agents.base import registry  # local import to avoid cycles
        agent = registry.get(long_id)
        if agent is not None:
            return getattr(agent, "system_prompt", "") or ""
    except Exception:
        pass
    return ""


@dataclass
class AgentRunResult:
    ok: bool
    agent_id: str
    output: str = ""
    error: Optional[str] = None
    duration_seconds: float = 0.0
    timed_out: bool = False


# ── output extraction helpers ─────────────────────────────────────────────

_BOX_LINE_RE = re.compile(r"^[\s│╭╮╯╰─━┃┏┓┗┛┣┫┳┻╋─-▟]+$")
_PROMPT_BOX_RE = re.compile(r"^[\s│]*>\s*$")
_HINT_LINE_RE = re.compile(r"\b(esc to interrupt|tokens?\b|context left|ctrl\+o to expand|^\s*\?\s+for shortcuts)", re.IGNORECASE)
# Post-response TUI chrome: timing line, feedback prompt, input caret, mode bar.
_RESPONSE_CHROME_RE = re.compile(
    r"^\s*(✻ Worked for\b|● How is Claude doing\b|⏵⏵|❯\s*$|\d+:\s*(Bad|Fine|Good|Dismiss)\b)"
)

_TRUST_DIALOG_MARKERS = (
    "trust this folder",
    "Is this a project you created",
    "Yes, I trust this folder",
)
_READY_MARKERS = (
    "│ >",
    "/help for",
    "Type a message",
    "type a message",
    "Try \"",
)


async def _wait_until_ready(sup, agent_id: str, timeout: float = 15.0) -> None:
    """After spawn, dismiss the workspace-trust dialog if present and wait for
    the main input prompt to render. Continues silently on timeout — the worst
    case is a captured banner that gets stripped from the response."""
    deadline = time.time() + timeout
    dismissed = False
    while time.time() < deadline:
        try:
            text = sup.capture(agent_id, lines=80)
        except Exception:
            await asyncio.sleep(0.4)
            continue
        if not dismissed and any(m in text for m in _TRUST_DIALOG_MARKERS):
            sup.send_keys(agent_id, "Enter")
            dismissed = True
            await asyncio.sleep(2.0)
            continue
        if any(m in text for m in _READY_MARKERS):
            return
        await asyncio.sleep(0.4)


def _strip_ui_chrome(text: str) -> str:
    """Drop pure box-drawing rows and TUI hint lines from captured output."""
    out: list[str] = []
    for ln in text.splitlines():
        if not ln.strip():
            out.append(ln)
            continue
        if _BOX_LINE_RE.match(ln):
            continue
        if _PROMPT_BOX_RE.match(ln):
            continue
        if _HINT_LINE_RE.search(ln):
            continue
        if _RESPONSE_CHROME_RE.match(ln):
            continue
        out.append(ln)
    return "\n".join(out)


def _delta_after_prompt(before: str, after: str, prompt: str) -> str:
    """Return the slice of `after` that came in after `before` was captured.

    Falls back to `after` if the buffer rolled and `before` is no longer a prefix.
    Then strips the prompt itself if the TUI echoed it back.
    """
    if before and after.startswith(before):
        delta = after[len(before):]
    else:
        delta = after
    # If the prompt was echoed back, drop the WHOLE echoed block: cut after the
    # prompt's last line when findable (the TUI indents but keeps line breaks),
    # else after the first line as before.
    prompt_lines = [l.strip() for l in prompt.strip().splitlines() if l.strip()]
    if prompt_lines and prompt_lines[0] in delta:
        idx = delta.find(prompt_lines[0])
        end = delta.find(prompt_lines[-1], idx)
        cut = end if end != -1 else idx
        nl = delta.find("\n", cut)
        if nl != -1:
            delta = delta[nl + 1:]
    return delta


# ── public API ────────────────────────────────────────────────────────────

async def run_agent_task(
    agent_id: str,
    prompt: str,
    *,
    timeout_seconds: int = 600,
    idle_seconds: int = 4,
    fresh_context: bool = False,
) -> AgentRunResult:
    """Run a prompt against an agent's persistent tmux session.

    Lazy-spawns the session on first call. On error, returns
    AgentRunResult(ok=False, error=...) with PATH context appended so caller
    logs are debuggable. On timeout, returns the partial output captured so far
    and sets ``timed_out=True``.
    """
    start = time.time()
    sup = get_supervisor()

    try:
        system_prompt = _resolve_system_prompt(agent_id) or (
            f"You are the {agent_id} agent of Borina Mesh."
        )
        # AGENT_REGISTRY may pin an agent to a fixed workdir (e.g. finance,
        # whose CLAUDE.md + BRIEF_FORMAT specs live in one canonical location).
        # Otherwise default to the per-pane scratch dir.
        registry_entry = AGENT_REGISTRY.get(agent_id, {})
        workdir = registry_entry.get("workdir") or str(_workdir_root() / agent_id)

        if fresh_context and sup.session_exists(agent_id):
            sup.kill(agent_id)

        spawned_now = False
        if not sup.session_exists(agent_id):
            sup.spawn(agent_id, workdir, system_prompt)
            spawned_now = True

        loop = asyncio.get_event_loop()

        if spawned_now:
            # Wait for the TUI to render and dismiss the workspace-trust dialog
            # if it appears — otherwise the first prompt would be eaten by the
            # modal selection prompt.
            await asyncio.sleep(2.5)
            await _wait_until_ready(sup, agent_id)

        before = await loop.run_in_executor(None, sup.capture, agent_id, 400)

        # Defensive: dismiss the workspace-trust dialog if it's still up
        # (e.g., the session was spawned by an older runner_v2).
        if any(m in before for m in _TRUST_DIALOG_MARKERS):
            sup.send_keys(agent_id, "Enter")
            await asyncio.sleep(2.0)
            before = await loop.run_in_executor(None, sup.capture, agent_id, 400)

        await loop.run_in_executor(None, sup.send_prompt, agent_id, prompt)

        captured = await loop.run_in_executor(
            None, sup.wait_for_idle, agent_id, idle_seconds, timeout_seconds,
        )

        delta = _delta_after_prompt(before, captured, prompt)
        cleaned = _strip_ui_chrome(delta).strip()

        elapsed = time.time() - start
        timed_out = elapsed >= max(timeout_seconds - 1, 1)
        return AgentRunResult(
            ok=True,
            agent_id=agent_id,
            output=cleaned,
            duration_seconds=elapsed,
            timed_out=timed_out,
        )
    except Exception as e:
        return AgentRunResult(
            ok=False,
            agent_id=agent_id,
            error=f"{type(e).__name__}: {e!r} | PATH={os.environ.get('PATH')}",
            duration_seconds=time.time() - start,
        )
