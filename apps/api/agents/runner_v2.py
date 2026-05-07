"""Drop-in replacement for the scheduled-job runner.

Replaces ad-hoc `claude` subprocess spawns with persistent tmux-hosted
sessions managed by `tmux_supervisor`. The session is lazy-spawned on the
first call for an agent and reused afterwards, which keeps the agent's
context across runs (matching how a human runs `claude` interactively).

Public API:
    result = await run_agent_task(agent_id, prompt, timeout_seconds=600,
                                  idle_seconds=4, fresh_context=False)
    if not result.ok:
        ...

`AGENT_REGISTRY` is the authoritative list of agents the runner knows how
to spawn for the current pane. Workdirs are pane-prefixed
(`~/.borina/agents/p{PANE_NUMBER}/{agent_id}/`) so parallel borina-mesh
worktrees don't share state.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from agents.tmux_supervisor import get_supervisor


# ── registry ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AgentSpec:
    """Maps a runner key (short canonical name) to a registered agent class id."""

    session_key: str         # tmux session key (also the workdir leaf)
    registered_id: str       # id used by agents.base.registry to look up system_prompt


# Canonical 7-agent roster. Keyed by short name; the verification suite
# uses "trader" which works as both a short name and the full id.
AGENT_REGISTRY: dict[str, AgentSpec] = {
    "trader":     AgentSpec(session_key="trader",     registered_id="trader"),
    "inbox":      AgentSpec(session_key="inbox",      registered_id="inbox-triage"),
    "scout":      AgentSpec(session_key="scout",      registered_id="ecommerce-scout"),
    "ceo":        AgentSpec(session_key="ceo",        registered_id="ceo"),
    "polymarket": AgentSpec(session_key="polymarket", registered_id="polymarket-intel"),
    "researcher": AgentSpec(session_key="researcher", registered_id="researcher"),
    "adset":      AgentSpec(session_key="adset",      registered_id="adset-optimizer"),
}


def _resolve_spec(agent_id: str) -> AgentSpec:
    """Accept either the short canonical key or the registered id."""
    if agent_id in AGENT_REGISTRY:
        return AGENT_REGISTRY[agent_id]
    for spec in AGENT_REGISTRY.values():
        if spec.registered_id == agent_id:
            return spec
    raise KeyError(
        f"agent '{agent_id}' is not in AGENT_REGISTRY. "
        f"Known: {sorted(AGENT_REGISTRY.keys())}"
    )


def _pane_number() -> str:
    return os.environ.get("PANE_NUMBER", "0")


def default_workdir(session_key: str) -> str:
    return os.path.expanduser(f"~/.borina/agents/p{_pane_number()}/{session_key}")


def default_system_prompt(registered_id: str) -> str:
    """Pull the system prompt off the registered Agent class. Empty string if absent."""
    try:
        from agents.base import registry
        agent = registry.get(registered_id)
        if agent is not None:
            return getattr(agent, "system_prompt", "") or ""
    except Exception:
        pass
    return ""


# ── result type ──────────────────────────────────────────────────────────


@dataclass
class AgentRunResult:
    ok: bool
    agent_id: str
    output: str = ""
    error: Optional[str] = None
    timed_out: bool = False
    duration_seconds: float = 0.0
    session: str = ""
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "agent_id": self.agent_id,
            "output": self.output,
            "error": self.error,
            "timed_out": self.timed_out,
            "duration_seconds": self.duration_seconds,
            "session": self.session,
            "metadata": self.metadata,
        }


# ── helpers ──────────────────────────────────────────────────────────────


def _diff_after_marker(before: str, after: str) -> str:
    """Return the suffix of `after` that appeared after `before`.

    Tmux `capture-pane` always returns the most-recent N lines, so simple
    string suffix-after-prefix gives us the new content emitted during the
    prompt-response cycle.
    """
    if before and before in after:
        idx = after.rfind(before)
        return after[idx + len(before):]
    return after


# ── public entry point ───────────────────────────────────────────────────


async def run_agent_task(
    agent_id: str,
    prompt: str,
    *,
    timeout_seconds: float = 600.0,
    idle_seconds: float = 4.0,
    fresh_context: bool = False,
    workdir: Optional[str] = None,
    system_prompt: Optional[str] = None,
) -> AgentRunResult:
    """Execute a prompt against the agent's persistent tmux session.

    Lazy-spawns the session on first call. Reuses it afterwards so context
    accumulates across runs. On timeout, returns the partial pane capture
    instead of raising. On any other error, returns ok=False with a typed
    error string and PATH for debugging in production.
    """
    import time

    started = time.time()
    try:
        spec = _resolve_spec(agent_id)
        session_key = spec.session_key
        wd = workdir or default_workdir(session_key)
        sys_prompt = system_prompt if system_prompt is not None else default_system_prompt(spec.registered_id)

        Path(wd).mkdir(parents=True, exist_ok=True)
        sup = get_supervisor()

        loop = asyncio.get_event_loop()

        if fresh_context and sup.session_exists(session_key):
            await loop.run_in_executor(None, sup.kill, session_key)

        # Lazy spawn (re-adopt if the session is already alive — supervisor handles this).
        await loop.run_in_executor(None, sup.spawn, session_key, wd, sys_prompt)

        # Snapshot before sending so we can diff to extract the response.
        before = await loop.run_in_executor(None, sup.capture, session_key, 400)

        # Initial spawn needs claude to finish booting before it accepts input.
        # Wait for a brief idle period so the TUI is ready.
        await loop.run_in_executor(None, sup.wait_for_idle, session_key, 1.5, 15.0, 0.3)

        await loop.run_in_executor(None, sup.send_prompt, session_key, prompt)

        captured = await loop.run_in_executor(
            None, sup.wait_for_idle, session_key, idle_seconds, timeout_seconds, 0.5,
        )

        elapsed = time.time() - started
        timed_out = elapsed >= timeout_seconds  # heuristic — wait_for_idle returns at deadline
        new_text = _diff_after_marker(before, captured)

        return AgentRunResult(
            ok=not timed_out,
            agent_id=agent_id,
            output=new_text.strip() or captured.strip(),
            error="timeout" if timed_out else None,
            timed_out=timed_out,
            duration_seconds=elapsed,
            session=sup.session_name(session_key),
            metadata={"workdir": wd, "registered_id": spec.registered_id},
        )

    except Exception as e:
        elapsed = time.time() - started
        return AgentRunResult(
            ok=False,
            agent_id=agent_id,
            output="",
            error=f"{type(e).__name__}: {e!r} | PATH={os.environ.get('PATH')}",
            duration_seconds=elapsed,
        )
