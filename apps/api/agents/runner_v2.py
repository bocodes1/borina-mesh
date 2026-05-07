"""Drop-in replacement for the old subprocess-per-call agent runner.

The old runner invoked `claude --print` as a fresh subprocess for every
scheduled job, paying full startup cost (~3-8s) and losing in-session
context. `runner_v2` keeps a long-lived tmux/`claude` session per agent
via :class:`agents.tmux_supervisor.TmuxSupervisor`, and reuses it.

Key contract:
    result = await run_agent_task("trader", "Run your daily check.")
    if result.ok:
        print(result.output)
    else:
        print(result.error)

`AgentRunResult` is a frozen dataclass so callers can pattern-match.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from agents.tmux_supervisor import get_supervisor, TmuxSupervisor


# ----------------------------------------------------------------------------
# Result type
# ----------------------------------------------------------------------------

@dataclass
class AgentRunResult:
    ok: bool
    agent_id: str
    output: str = ""
    error: str = ""
    timed_out: bool = False
    elapsed_seconds: float = 0.0
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "agent_id": self.agent_id,
            "output": self.output,
            "error": self.error,
            "timed_out": self.timed_out,
            "elapsed_seconds": self.elapsed_seconds,
            "metadata": self.metadata,
        }


# ----------------------------------------------------------------------------
# Agent registry
# ----------------------------------------------------------------------------

# Each agent's default system prompt is loaded lazily from agents.base.registry
# (so we don't duplicate it here), but the registry below holds the metadata
# needed to spawn a session: workdir tail and a fallback system prompt.

AGENT_REGISTRY: dict[str, dict] = {
    "trader": {
        "subdir": "trader",
        "fallback_prompt": "You are the Trader agent — risk-paranoid trade analysis.",
    },
    "inbox-triage": {
        "subdir": "inbox",
        "fallback_prompt": "You are the Inbox Triage agent — ruthless message prioritization.",
    },
    "ecommerce-scout": {
        "subdir": "scout",
        "fallback_prompt": "You are the Ecommerce Scout — product discovery via Computer Use.",
    },
    "ceo": {
        "subdir": "ceo",
        "fallback_prompt": "You are the CEO agent — strategic synthesizer.",
    },
    "polymarket-intel": {
        "subdir": "polymarket",
        "fallback_prompt": "You are the Polymarket Intel agent — leaderboard/whale analysis.",
    },
    "researcher": {
        "subdir": "researcher",
        "fallback_prompt": "You are the Researcher agent — verified-source deep research.",
    },
    "adset-optimizer": {
        "subdir": "adset",
        "fallback_prompt": "You are the Adset Optimizer agent — ROI-focused ad analysis.",
    },
}

# Compatibility aliases for older identifiers that may show up in scheduled
# jobs or stored config. Add here, don't sprinkle through callers.
AGENT_ALIASES: dict[str, str] = {
    "inbox": "inbox-triage",
    "scout": "ecommerce-scout",
    "polymarket": "polymarket-intel",
    "adset": "adset-optimizer",
}


def _canonical_agent_id(agent_id: str) -> str:
    return AGENT_ALIASES.get(agent_id, agent_id)


def _agent_workdir(agent_id: str) -> Path:
    """Pane-prefixed workdir under ~/.borina/agents/p{N}/{subdir}."""
    pane = os.environ.get("BORINA_PANE_NUM", "0").strip() or "0"
    base = Path(os.environ.get("BORINA_AGENT_HOME", str(Path.home() / ".borina" / "agents")))
    subdir = AGENT_REGISTRY.get(agent_id, {}).get("subdir", agent_id)
    workdir = base / f"p{pane}" / subdir
    workdir.mkdir(parents=True, exist_ok=True)
    return workdir


def _resolve_system_prompt(agent_id: str) -> str:
    """Pull the system prompt from the live agent registry, with fallback.

    We read `agents.base.registry` lazily so this module has no import-time
    dependency on the agents being loaded — important for tests.
    """
    try:
        from agents.base import registry as _agent_registry
        agent = _agent_registry.get(agent_id)
        if agent is not None and getattr(agent, "system_prompt", ""):
            return agent.system_prompt
    except Exception:
        pass
    return AGENT_REGISTRY.get(agent_id, {}).get("fallback_prompt", "")


# ----------------------------------------------------------------------------
# Public entrypoint
# ----------------------------------------------------------------------------

async def run_agent_task(
    agent_id: str,
    prompt: str,
    *,
    timeout_seconds: float = 600.0,
    idle_seconds: float = 4.0,
    fresh_context: bool = False,
) -> AgentRunResult:
    """Run a prompt through the agent's long-lived claude session.

    Lazy-spawns the tmux session on first call. On error, returns a
    populated :class:`AgentRunResult` with a typed error string instead of
    raising — callers should branch on `result.ok`.

    Parameters
    ----------
    agent_id: registered agent slug (canonical or alias).
    prompt: full user message to send. Multi-line is supported.
    timeout_seconds: max wall time to wait for a response (returns partial on timeout).
    idle_seconds: seconds of unchanged pane that count as "response complete".
    fresh_context: if True, restart the agent's session before sending —
        useful when the previous turn left the pane in a bad state.
    """
    canonical = _canonical_agent_id(agent_id)
    if canonical not in AGENT_REGISTRY:
        return AgentRunResult(
            ok=False,
            agent_id=agent_id,
            error=(
                f"UnknownAgent: {agent_id!r} is not in AGENT_REGISTRY "
                f"(known={sorted(AGENT_REGISTRY)}) | "
                f"PATH={os.environ.get('PATH')}"
            ),
        )

    loop = asyncio.get_event_loop()
    started_at = loop.time()

    def _do_work() -> AgentRunResult:
        sup: TmuxSupervisor = get_supervisor()
        workdir = str(_agent_workdir(canonical))
        system_prompt = _resolve_system_prompt(canonical)

        try:
            if fresh_context and sup.session_exists(canonical):
                sup.restart(canonical)
            else:
                sup.spawn(canonical, workdir, system_prompt)
        except Exception as e:
            return AgentRunResult(
                ok=False,
                agent_id=agent_id,
                error=f"{type(e).__name__}: {e!r} | PATH={os.environ.get('PATH')}",
                metadata={"phase": "spawn"},
            )

        # Snapshot the pane right before sending so we can diff to extract
        # only this turn's output.
        try:
            before = sup.capture(canonical, lines=400)
        except Exception:
            before = ""

        # Send the prompt.
        try:
            sup.send_prompt(canonical, prompt)
        except Exception as e:
            return AgentRunResult(
                ok=False,
                agent_id=agent_id,
                error=f"{type(e).__name__}: {e!r} | PATH={os.environ.get('PATH')}",
                metadata={"phase": "send"},
            )

        # Wait for idle, capturing partial on timeout.
        try:
            after = sup.wait_for_idle(
                canonical,
                idle_seconds=idle_seconds,
                timeout_seconds=timeout_seconds,
            )
        except Exception as e:
            try:
                partial = sup.capture(canonical, lines=400)
            except Exception:
                partial = ""
            return AgentRunResult(
                ok=False,
                agent_id=agent_id,
                error=f"{type(e).__name__}: {e!r} | PATH={os.environ.get('PATH')}",
                output=partial,
                metadata={"phase": "wait"},
            )

        elapsed = loop.time() - started_at
        timed_out = elapsed >= timeout_seconds

        # Compute the new content as best we can: diff before/after.
        delta = _diff_pane(before, after)

        return AgentRunResult(
            ok=not timed_out or bool(delta.strip()),
            agent_id=agent_id,
            output=delta if delta.strip() else after,
            timed_out=timed_out,
            elapsed_seconds=elapsed,
            metadata={"phase": "ok" if not timed_out else "timeout-partial"},
        )

    # Run the blocking tmux work in a thread so we don't block the event loop.
    return await loop.run_in_executor(None, _do_work)


def _diff_pane(before: str, after: str) -> str:
    """Return the suffix of `after` that wasn't already in `before`.

    Tmux pane captures are sliding windows; the safest "what's new since
    we sent the prompt" heuristic is: find the longest suffix of `before`
    that appears in `after`, then return everything after that match.
    Falls back to returning all of `after` if no overlap is found.
    """
    if not before:
        return after
    if not after:
        return ""
    # Try progressively shorter tails of `before` to find the join point.
    # Cap at 4000 chars so we don't pathologically scan huge buffers.
    tail_lengths = [4000, 1000, 200, 50]
    for n in tail_lengths:
        if n >= len(before):
            n = len(before)
        anchor = before[-n:]
        idx = after.rfind(anchor)
        if idx != -1:
            return after[idx + len(anchor):]
    return after
