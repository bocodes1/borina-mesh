"""Drop-in replacement for the scheduled agent job runner.

Uses tmux-supervised long-lived ``claude`` REPL sessions instead of one-shot
``claude -p`` subprocesses. Each agent has its own pane-namespaced workdir so
parallel pane instances of the refactor never share state.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from pathlib import Path

from agents.tmux_supervisor import SessionInfo, get_supervisor


PANE_NUMBER = os.environ.get("BORINA_PANE_NUMBER", "0")
BASE_WORKDIR = Path.home() / ".borina" / "agents" / f"p{PANE_NUMBER}"


@dataclass(frozen=True)
class AgentSpec:
    agent_id: str
    name: str
    system_prompt: str


AGENT_REGISTRY: dict[str, AgentSpec] = {
    "trader": AgentSpec(
        agent_id="trader",
        name="Trader",
        system_prompt=(
            "You are the Trader agent of Borina Mesh. Risk-paranoid trade analysis. "
            "Every recommendation includes worst-case scenario, entry/target/stop, "
            "and position sizing under daily loss limits."
        ),
    ),
    "inbox": AgentSpec(
        agent_id="inbox",
        name="Inbox Triage",
        system_prompt=(
            "You are the Inbox Triage agent. Surface urgent emails and Telegram "
            "messages, draft replies, and group similar threads."
        ),
    ),
    "scout": AgentSpec(
        agent_id="scout",
        name="Ecommerce Scout",
        system_prompt=(
            "You are the Ecommerce Scout agent. Find winning products from "
            "KaloData and similar trend trackers and summarise what is breaking out."
        ),
    ),
    "ceo": AgentSpec(
        agent_id="ceo",
        name="CEO",
        system_prompt=(
            "You are the CEO agent. Strategic morning briefing — top priorities, "
            "blockers, and decisions needed today."
        ),
    ),
    "polymarket": AgentSpec(
        agent_id="polymarket",
        name="Polymarket Intel",
        system_prompt=(
            "You are the Polymarket Intel agent. Leaderboard scan, whale flow, and "
            "signal synthesis for prediction markets."
        ),
    ),
    "researcher": AgentSpec(
        agent_id="researcher",
        name="Researcher",
        system_prompt=(
            "You are the Researcher agent. Deep multi-source research with citations "
            "and credibility scoring."
        ),
    ),
    "adset": AgentSpec(
        agent_id="adset",
        name="Adset Optimizer",
        system_prompt=(
            "You are the Adset Optimizer agent. GMC ad rotation, creative analysis, "
            "and budget reallocation across active campaigns."
        ),
    ),
}


# Long-form agent IDs used by scheduler.py mapped to runner_v2's short IDs.
AGENT_ALIASES: dict[str, str] = {
    "ecommerce-scout": "scout",
    "polymarket-intel": "polymarket",
    "adset-optimizer": "adset",
    "inbox-triage": "inbox",
}


def resolve_runner_id(agent_id: str) -> str:
    """Translate a long-form agent ID to runner_v2's short canonical ID."""
    return AGENT_ALIASES.get(agent_id, agent_id)


@dataclass
class AgentRunResult:
    agent_id: str
    ok: bool
    output: str = ""
    error: str = ""
    duration_seconds: float = 0.0
    timed_out: bool = False
    session_name: str = ""


def _workdir_for(agent_id: str) -> Path:
    p = BASE_WORKDIR / agent_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def _ensure_session(agent_id: str, *, fresh_context: bool) -> SessionInfo:
    if agent_id not in AGENT_REGISTRY:
        raise KeyError(
            f"agent {agent_id!r} is not in AGENT_REGISTRY; "
            f"known agents: {sorted(AGENT_REGISTRY)}"
        )
    spec = AGENT_REGISTRY[agent_id]
    sup = get_supervisor()
    if fresh_context and sup.session_exists(agent_id):
        sup.kill(agent_id)
    return sup.spawn(agent_id, str(_workdir_for(agent_id)), spec.system_prompt)


def _diff_response(before: str, after: str) -> str:
    """Return the part of ``after`` that wasn't already in ``before``.

    Tmux capture is a rolling buffer, so ``after`` typically begins with the same tail
    text as ``before`` plus new content appended. We take the longest suffix-of-before
    that is also a prefix-of-after and slice everything past it.
    """
    if not before:
        return after.strip()
    if after.startswith(before):
        return after[len(before):].strip()
    upper = min(len(before), len(after))
    for i in range(upper, 0, -1):
        if after.startswith(before[-i:]):
            return after[i:].strip()
    return after.strip()


def _run_agent_task_sync(
    agent_id: str,
    prompt: str,
    *,
    timeout_seconds: float,
    idle_seconds: float,
    fresh_context: bool,
) -> AgentRunResult:
    start = time.monotonic()
    session_name = ""
    try:
        info = _ensure_session(agent_id, fresh_context=fresh_context)
        session_name = info.session_name
        sup = get_supervisor()

        # Allow first-time spawns a moment to print the welcome banner before we
        # snapshot the "before" state. Cheap to wait, expensive to truncate.
        time.sleep(1.5)
        before = sup.capture(agent_id, lines=400)

        sup.send_prompt(agent_id, prompt)

        final = sup.wait_for_idle(
            agent_id,
            idle_seconds=idle_seconds,
            timeout_seconds=timeout_seconds,
        )
        response = _diff_response(before, final)

        duration = time.monotonic() - start
        timed_out = duration >= timeout_seconds

        return AgentRunResult(
            agent_id=agent_id,
            ok=not timed_out,
            output=response,
            error=("timed out — partial output returned" if timed_out else ""),
            duration_seconds=duration,
            timed_out=timed_out,
            session_name=session_name,
        )
    except Exception as e:
        return AgentRunResult(
            agent_id=agent_id,
            ok=False,
            output="",
            error=f"{type(e).__name__}: {e!r} | PATH={os.environ.get('PATH')}",
            duration_seconds=time.monotonic() - start,
            session_name=session_name,
        )


async def run_agent_task(
    agent_id: str,
    prompt: str,
    *,
    timeout_seconds: float = 600,
    idle_seconds: float = 4,
    fresh_context: bool = False,
) -> AgentRunResult:
    """Run a prompt through the agent's persistent tmux-supervised claude session.

    Lazy-spawns the session on first call. On timeout, returns whatever output was
    captured (``ok=False`` + ``timed_out=True``). On any other failure, returns a
    typed error message that includes ``PATH`` so misconfigured environments are
    diagnosable from the response alone.
    """
    return await asyncio.to_thread(
        _run_agent_task_sync,
        agent_id,
        prompt,
        timeout_seconds=timeout_seconds,
        idle_seconds=idle_seconds,
        fresh_context=fresh_context,
    )
