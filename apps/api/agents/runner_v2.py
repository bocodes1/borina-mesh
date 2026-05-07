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

_PANE_NUMBER = os.environ.get("BORINA_PANE_NUMBER", "1")
WORKDIR_ROOT = Path.home() / ".borina" / "agents" / f"p{_PANE_NUMBER}"


# ── default registry ──────────────────────────────────────────────────────
# Keys are the agent IDs accepted by run_agent_task. Values are spawn metadata.
# system_prompt is appended to claude's default system prompt at spawn time.

AGENT_REGISTRY: dict[str, dict] = {
    "trader": {
        "system_prompt": (
            "You are the Trader agent of Borina Mesh. Risk-paranoid: every "
            "trade idea includes worst-case scenario. Output is terse and exact."
        ),
    },
    "inbox": {
        "system_prompt": (
            "You are the Inbox Triage agent. Summarise emails and Telegrams "
            "into one-line briefs sorted by urgency. No preamble."
        ),
    },
    "scout": {
        "system_prompt": (
            "You are the Ecommerce Scout. Find winning products with strong "
            "margin and emerging demand. Cite sources. No fluff."
        ),
    },
    "ceo": {
        "system_prompt": (
            "You are the CEO agent. Produce a strategic morning briefing: "
            "what changed, what to do today, what's blocked."
        ),
    },
    "polymarket": {
        "system_prompt": (
            "You are the Polymarket Intel agent. Synthesise leaderboard "
            "and whale signals into actionable trade ideas with risk."
        ),
    },
    "researcher": {
        "system_prompt": (
            "You are the Researcher. Aggregate the morning brief: news, "
            "papers, repos, market moves. Cite, deduplicate, prioritise."
        ),
    },
    "adset": {
        "system_prompt": (
            "You are the Adset Optimizer. Rotate Google/Meta ad creatives "
            "based on yesterday's performance. Numbers exact, recommendations sharp."
        ),
    },
}


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
_HINT_LINE_RE = re.compile(r"\b(esc to interrupt|tokens?\b|context left|^\s*\?\s+for shortcuts)", re.IGNORECASE)

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
    # If the prompt appears verbatim in the delta, drop everything up to and
    # including its first line — the response follows.
    first_prompt_line = prompt.strip().splitlines()[0] if prompt.strip() else ""
    if first_prompt_line and first_prompt_line in delta:
        idx = delta.find(first_prompt_line)
        # Move past the line containing the echoed prompt.
        nl = delta.find("\n", idx)
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
        registration = AGENT_REGISTRY.get(agent_id, {})
        system_prompt = registration.get(
            "system_prompt", f"You are the {agent_id} agent of Borina Mesh."
        )
        workdir = str(WORKDIR_ROOT / agent_id)

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
