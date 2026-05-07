"""Async drop-in replacement for the scheduled-job claude runner.

Replaces the previous `claude -p` per-call subprocess pattern with a long-lived
tmux REPL pool managed by `tmux_supervisor`. Each agent gets its own session,
warm context, and pane-prefixed workdir so the 8 parallel refactor instances
don't share state.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from agents.tmux_supervisor import (
    TmuxSupervisor,
    get_supervisor,
    _detect_pane_number,
)


# ---------------------------------------------------------------------------
# Agent registry — short alias → long id used by `agents.base.registry`.
# The system_prompt is resolved dynamically from the agent class so it stays
# in sync with the source of truth (no copy-paste drift).
# ---------------------------------------------------------------------------
AGENT_REGISTRY: dict[str, dict] = {
    "trader":     {"long_id": "trader",            "label": "Trader"},
    "inbox":      {"long_id": "inbox-triage",      "label": "Inbox Triage"},
    "scout":      {"long_id": "ecommerce-scout",   "label": "Ecommerce Scout"},
    "ceo":        {"long_id": "ceo",               "label": "CEO"},
    "polymarket": {"long_id": "polymarket-intel",  "label": "Polymarket Intel"},
    "researcher": {"long_id": "researcher",        "label": "Researcher"},
    "adset":      {"long_id": "adset-optimizer",   "label": "Adset Optimizer"},
}


@dataclass
class AgentRunResult:
    """Outcome of a single run_agent_task call."""

    ok: bool
    agent_id: str
    output: str = ""
    error: str = ""
    timed_out: bool = False
    duration_s: float = 0.0
    session_name: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def workdir_for(agent_id: str, pane_number: Optional[str] = None) -> Path:
    """Pane-prefixed workdir so 8 parallel instances don't share state."""
    pn = pane_number or _detect_pane_number()
    return Path.home() / ".borina" / "agents" / f"p{pn}" / agent_id


def normalize_agent_id(agent_id: str) -> str:
    """Accept either the short alias (`trader`) or the long class id (`trader-x`).

    Returns the canonical short alias. Raises KeyError if neither matches —
    callers get a typed error rather than silent fallthrough.
    """
    if agent_id in AGENT_REGISTRY:
        return agent_id
    for short, info in AGENT_REGISTRY.items():
        if info["long_id"] == agent_id:
            return short
    raise KeyError(
        f"Unknown agent_id {agent_id!r}; valid short ids: {sorted(AGENT_REGISTRY)} "
        f"or long ids: {sorted(v['long_id'] for v in AGENT_REGISTRY.values())}"
    )


def _resolve_system_prompt(long_id: str) -> str:
    """Look up the agent class's system_prompt from the existing registry."""
    try:
        from agents.base import registry  # local import to avoid cycles
        agent = registry.get(long_id)
        if agent is not None:
            return getattr(agent, "system_prompt", "") or ""
    except Exception:
        pass
    return ""


def _ensure_session(
    supervisor: TmuxSupervisor,
    agent_id: str,
    *,
    fresh_context: bool,
) -> str:
    """Lazy-spawn or restart the agent's tmux session. Returns session name."""
    entry = AGENT_REGISTRY.get(agent_id)
    if not entry:
        raise KeyError(
            f"Unknown agent_id {agent_id!r}; valid ids: {sorted(AGENT_REGISTRY)}"
        )
    long_id = entry["long_id"]
    workdir = workdir_for(agent_id, supervisor.pane_number)
    system_prompt = _resolve_system_prompt(long_id)

    if fresh_context and supervisor.session_exists(agent_id):
        supervisor.kill(agent_id)

    if not supervisor.session_exists(agent_id):
        supervisor.spawn(agent_id, str(workdir), system_prompt)
        # Give claude a moment to print its prompt before we send anything.
        # The first wait_for_idle in run_agent_task will handle the rest.
        time.sleep(1.5)
    else:
        # Re-adopt: ensure supervisor has metadata in case API was restarted.
        supervisor.spawn(agent_id, str(workdir), system_prompt)

    return supervisor.session_name(agent_id)


def _extract_response(before_text: str, after_text: str, prompt: str) -> str:
    """Best-effort extraction of just the model's response.

    The simplest reliable heuristic: anything in `after_text` that wasn't in
    `before_text`. This trims the long-running scrollback so the caller doesn't
    have to parse Claude's TUI chrome themselves.
    """
    if not after_text:
        return ""
    # If before_text is a strict prefix, slice it off.
    if before_text and after_text.startswith(before_text):
        new_part = after_text[len(before_text):]
    else:
        # Find the longest suffix of before_text that is a prefix of after_text;
        # the remainder of after_text is what was added.
        for n in range(min(len(before_text), len(after_text)), 0, -1):
            if before_text.endswith(after_text[:n]):
                new_part = after_text[n:]
                break
        else:
            new_part = after_text
    new_part = new_part.strip()
    # If the prompt itself echoed back, drop the first occurrence — it's noise.
    if prompt and prompt in new_part:
        new_part = new_part.replace(prompt, "", 1).strip()
    return new_part


async def run_agent_task(
    agent_id: str,
    prompt: str,
    *,
    timeout_seconds: int = 600,
    idle_seconds: int = 4,
    fresh_context: bool = False,
) -> AgentRunResult:
    """Send `prompt` to the agent and wait for the response.

    Lazy-spawns the agent's tmux session on first call. Returns partial output
    on timeout (never a hard failure for a slow run).
    """
    started = time.monotonic()
    supervisor = get_supervisor()
    session_name = ""

    try:
        agent_id = normalize_agent_id(agent_id)
        # All blocking tmux work goes through the default executor.
        session_name = await asyncio.to_thread(
            _ensure_session, supervisor, agent_id, fresh_context=fresh_context
        )

        before_text = await asyncio.to_thread(supervisor.capture, agent_id, 400)
        await asyncio.to_thread(supervisor.send_prompt, agent_id, prompt)

        after_text = await asyncio.to_thread(
            supervisor.wait_for_idle,
            agent_id,
            float(idle_seconds),
            float(timeout_seconds),
        )

        elapsed = time.monotonic() - started
        timed_out = elapsed >= float(timeout_seconds)
        response = _extract_response(before_text, after_text, prompt)

        return AgentRunResult(
            ok=not timed_out,
            agent_id=agent_id,
            output=response,
            timed_out=timed_out,
            duration_s=round(elapsed, 3),
            session_name=session_name,
            error="" if not timed_out else (
                f"TimeoutError: idle wait exceeded {timeout_seconds}s"
            ),
        )

    except Exception as e:
        # Typed, contextual error — never empty.
        err = (
            f"{type(e).__name__}: {e!r} "
            f"| PATH={os.environ.get('PATH', '')}"
        )
        return AgentRunResult(
            ok=False,
            agent_id=agent_id,
            output="",
            error=err,
            timed_out=False,
            duration_s=round(time.monotonic() - started, 3),
            session_name=session_name,
        )
