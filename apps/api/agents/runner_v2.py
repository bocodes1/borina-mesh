"""Drop-in replacement for the scheduled-job claude runner.

`run_agent_task()` is the single entrypoint: it lazily spawns a long-lived
tmux/claude session for the agent, sends the prompt, waits for the REPL
to go idle, and returns whatever output was produced.  On failure or
timeout, it returns an `AgentRunResult` with `ok=False` and the partial
capture; it never raises out to the caller.

This module replaces the previous flow that spun up a fresh `claude`
subprocess (or `claude_agent_sdk.query()` task) for every job.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agents.tmux_supervisor import get_supervisor


def _pane_number() -> str:
    return os.environ.get("BORINA_PANE_NUMBER", "0")


def _agent_workdir(agent_id: str) -> str:
    base = Path(
        os.path.expanduser(f"~/.borina/agents/p{_pane_number()}/{agent_id}")
    )
    base.mkdir(parents=True, exist_ok=True)
    return str(base)


# Default per-agent registry.  `system_prompt` is filled in lazily from
# `agents.base.registry` if the agent is registered there; otherwise it
# falls back to the literal string set here.
AGENT_REGISTRY: dict[str, dict[str, Any]] = {
    "trader":     {"workdir": None, "system_prompt": "You are the Trader agent."},
    "inbox":      {"workdir": None, "system_prompt": "You are the Inbox Triage agent."},
    "scout":      {"workdir": None, "system_prompt": "You are the Ecommerce Scout agent."},
    "ceo":        {"workdir": None, "system_prompt": "You are the CEO agent."},
    "polymarket": {"workdir": None, "system_prompt": "You are the Polymarket Intel agent."},
    "researcher": {"workdir": None, "system_prompt": "You are the Researcher agent."},
    "adset":      {"workdir": None, "system_prompt": "You are the Adset Optimizer agent."},
}


@dataclass
class AgentRunResult:
    ok: bool
    output: str = ""
    error: str = ""
    agent_id: str = ""
    timed_out: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


def _resolve_config(agent_id: str) -> dict[str, Any]:
    """Build the spawn config for an agent: workdir + system_prompt."""
    base = AGENT_REGISTRY.get(agent_id, {})
    workdir = base.get("workdir") or _agent_workdir(agent_id)
    system_prompt = base.get("system_prompt") or ""
    # Pull the rich system prompt from the live agent registry if available.
    try:
        from agents.base import registry as _live_registry  # type: ignore
        live = _live_registry.get(agent_id)
        if live and getattr(live, "system_prompt", ""):
            system_prompt = live.system_prompt
    except Exception:
        pass
    return {"workdir": workdir, "system_prompt": system_prompt}


def _diff_output(before: str, after: str, prompt: str | None = None) -> str:
    """Return the new content rendered in the pane since `before`.

    Strategy in order:
      1. If `before` appears verbatim in `after`, return what comes after.
      2. If we can find the user's prompt line (`❯ <prompt>`) in `after`,
         return everything below it (the assistant's response area).
      3. Otherwise return `after` whole — let the caller see the full
         capture rather than guess wrong and strip the response.

    The previous line-suffix fallback was too eager: status-bar lines
    that occur in both captures matched and chopped the response off."""
    if not before:
        return after
    if before in after:
        return after.split(before, 1)[-1]
    if prompt:
        # Use the first ~60 chars of the prompt as a marker; tmux wraps long
        # lines, so a long-line search misses.  The REPL renders user input
        # prefixed with `❯ ` (heavy right angle bracket).
        marker = prompt.strip().splitlines()[0][:60]
        for needle in (f"❯ {marker}", marker):
            if needle and needle in after:
                return after.split(needle, 1)[-1]
    return after


async def run_agent_task(
    agent_id: str,
    prompt: str,
    *,
    timeout_seconds: int = 600,
    idle_seconds: int = 4,
    fresh_context: bool = False,
) -> AgentRunResult:
    """Run `prompt` against the agent's tmux/claude session and return its output."""
    loop = asyncio.get_event_loop()

    try:
        supervisor = get_supervisor()
        cfg = _resolve_config(agent_id)

        if fresh_context and supervisor.session_exists(agent_id):
            await loop.run_in_executor(None, supervisor.kill, agent_id)

        if not supervisor.session_exists(agent_id):
            await loop.run_in_executor(
                None,
                supervisor.spawn,
                agent_id,
                cfg["workdir"],
                cfg["system_prompt"],
            )
            # Settle: let the REPL render its prompt before typing.
            await asyncio.sleep(1.5)

        before = await loop.run_in_executor(
            None, supervisor.capture, agent_id, 800
        )
        await loop.run_in_executor(
            None, supervisor.send_prompt, agent_id, prompt
        )
        final = await loop.run_in_executor(
            None,
            supervisor.wait_for_idle,
            agent_id,
            float(idle_seconds),
            float(timeout_seconds),
        )

        delta = _diff_output(before, final, prompt=prompt)
        return AgentRunResult(
            ok=True,
            output=delta,
            agent_id=agent_id,
            extra={"raw": final},
        )

    except Exception as e:
        # Best-effort partial capture so the caller sees whatever did make it.
        partial = ""
        try:
            partial = get_supervisor().capture(agent_id, 800)
        except Exception:
            pass
        return AgentRunResult(
            ok=False,
            output=partial,
            agent_id=agent_id,
            error=f"{type(e).__name__}: {e!r} | PATH={os.environ.get('PATH')}",
        )
