"""Tmux-backed agent runner — drop-in replacement for the scheduled job runner.

The scheduler used to call `agent.stream()` (claude_agent_sdk subprocess); now it
calls `run_agent_task()`, which lazily owns a long-lived tmux session per agent
and pastes prompts into the live `claude` TUI inside it.

Workdirs are pane-namespaced under `~/.borina/agents/p<N>/<agent_id>/` so
multiple parallel refactor instances on the same machine don't share state.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from agents.tmux_supervisor import get_supervisor

PANE_NUMBER = os.environ.get("BORINA_PANE_NUMBER", "0")
WORKDIR_ROOT = Path(os.path.expanduser(f"~/.borina/agents/p{PANE_NUMBER}"))


# Maps the short runner-facing agent id to the canonical agent id used by the
# pre-existing `agents.base.registry` (whose system_prompts we re-use).
_INTERNAL_ID_MAP = {
    "trader": "trader",
    "inbox": "inbox-triage",
    "scout": "ecommerce-scout",
    "ceo": "ceo",
    "polymarket": "polymarket-intel",
    "researcher": "researcher",
    "adset": "adset-optimizer",
}

# Reverse: lets the scheduler hand us its long-form ids (e.g. "ecommerce-scout")
# without forcing every caller to translate.
_FULL_TO_SHORT = {full: short for short, full in _INTERNAL_ID_MAP.items()}


def _normalize_agent_id(agent_id: str) -> str:
    """Accept either short ('scout') or full ('ecommerce-scout') ids."""
    return _FULL_TO_SHORT.get(agent_id, agent_id)


def _default_workdir(agent_id: str) -> str:
    return str(WORKDIR_ROOT / agent_id)


def _resolve_system_prompt(agent_id: str) -> str:
    """Pull system_prompt from the existing agent registry; fall back to a stub."""
    internal = _INTERNAL_ID_MAP.get(agent_id, agent_id)
    try:
        from agents.base import registry
        agent = registry.get(internal)
        if agent and getattr(agent, "system_prompt", None):
            return str(agent.system_prompt)
    except Exception:
        pass
    return f"You are the {agent_id} agent of Borina Mesh."


# Public registry. Each entry is resolved lazily so the system_prompt picks up
# any edits made to the underlying agent class without a re-import.
AGENT_REGISTRY: dict[str, dict] = {
    "trader":     {"display": "Trader",     "internal_id": "trader"},
    "inbox":      {"display": "Inbox",      "internal_id": "inbox-triage"},
    "scout":      {"display": "Scout",      "internal_id": "ecommerce-scout"},
    "ceo":        {"display": "CEO",        "internal_id": "ceo"},
    "polymarket": {"display": "Polymarket", "internal_id": "polymarket-intel"},
    "researcher": {"display": "Researcher", "internal_id": "researcher"},
    "adset":      {"display": "Adset",      "internal_id": "adset-optimizer"},
}


@dataclass
class AgentRunResult:
    ok: bool
    agent_id: str
    prompt: str
    output: str = ""
    error: Optional[str] = None
    duration_seconds: float = 0.0
    timed_out: bool = False
    session_name: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _ensure_session(agent_id: str) -> str:
    """Spawn (or re-adopt) the agent's tmux session; return its name."""
    sup = get_supervisor()
    if not sup.session_exists(agent_id):
        cfg = AGENT_REGISTRY.get(agent_id)
        if cfg is None:
            raise RuntimeError(
                f"unknown agent {agent_id!r} — registered: {sorted(AGENT_REGISTRY)}"
            )
        workdir = _default_workdir(agent_id)
        Path(workdir).mkdir(parents=True, exist_ok=True)
        sup.spawn(agent_id, workdir, _resolve_system_prompt(agent_id))
        # Give the TUI a moment to draw its first frame so wait_for_idle has a
        # stable baseline before the user's first prompt.
        time.sleep(2.0)
    return sup._session_name(agent_id)


def _diff_output(before: str, after: str) -> str:
    """Best-effort: return the new tail that appeared between two captures.

    Falls back to the full `after` if no clean overlap is found.
    """
    if not before:
        return after
    # Look for the last line of `before` inside `after` and return everything after it.
    before_tail = before.rstrip().splitlines()
    if not before_tail:
        return after
    last = before_tail[-1]
    after_lines = after.splitlines()
    for i in range(len(after_lines) - 1, -1, -1):
        if after_lines[i] == last:
            return "\n".join(after_lines[i + 1:])
    return after


def _run_agent_task_sync(
    agent_id: str,
    prompt: str,
    timeout_seconds: float,
    idle_seconds: float,
    fresh_context: bool,
) -> AgentRunResult:
    """Blocking implementation that the async wrapper offloads to a thread."""
    started = time.time()
    sup = get_supervisor()
    try:
        if fresh_context and sup.session_exists(agent_id):
            sup.kill(agent_id)
        session_name = _ensure_session(agent_id)

        before = sup.capture(agent_id, lines=400)
        sup.send_prompt(agent_id, prompt)
        idle_reached, after = sup.wait_for_idle(
            agent_id,
            idle_seconds=idle_seconds,
            timeout_seconds=timeout_seconds,
        )
        new_text = _diff_output(before, after)

        if not idle_reached:
            return AgentRunResult(
                ok=True,
                agent_id=agent_id,
                prompt=prompt,
                output=new_text,
                error=None,
                duration_seconds=round(time.time() - started, 3),
                timed_out=True,
                session_name=session_name,
            )
        return AgentRunResult(
            ok=True,
            agent_id=agent_id,
            prompt=prompt,
            output=new_text,
            duration_seconds=round(time.time() - started, 3),
            session_name=session_name,
        )
    except Exception as e:
        return AgentRunResult(
            ok=False,
            agent_id=agent_id,
            prompt=prompt,
            output="",
            error=f"{type(e).__name__}: {e!r} | PATH={os.environ.get('PATH')}",
            duration_seconds=round(time.time() - started, 3),
        )


async def run_agent_task(
    agent_id: str,
    prompt: str,
    *,
    timeout_seconds: float = 600.0,
    idle_seconds: float = 4.0,
    fresh_context: bool = False,
) -> AgentRunResult:
    """Send `prompt` to the agent's tmux-hosted claude session and await the response.

    On timeout, returns the partial output captured so far (ok=True, timed_out=True)
    instead of raising — callers care about the bytes, not the deadline.
    On error, returns ok=False with a typed, fully-formatted error string that
    includes the current PATH for postmortem.
    """
    return await asyncio.to_thread(
        _run_agent_task_sync,
        _normalize_agent_id(agent_id),
        prompt,
        timeout_seconds,
        idle_seconds,
        fresh_context,
    )
