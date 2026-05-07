"""Drop-in replacement for the scheduled-job claude runner.

Instead of spawning a fresh `claude` subprocess (or invoking the SDK) for every
scheduled run, we keep one long-lived `claude` session per agent inside tmux.
Prompts are written into the session and we wait for the pane to go idle to
detect a complete response.

The public surface is intentionally tiny:

    result = await run_agent_task(agent_id, prompt)

It returns an `AgentRunResult` with `ok`, `output`, `error`, plus metadata.
On any failure the result includes the exception type and `repr(e)` along
with the current PATH so missing-binary issues are easy to diagnose.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from agents.tmux_supervisor import get_supervisor, PANE_NUMBER

# Per-pane workdir root so the eight parallel refactor instances do not
# share state on disk. Real session homes live under
# ~/.borina/agents/p{PANE}/{agent_id}/
_AGENTS_HOME = Path.home() / ".borina" / "agents" / f"p{PANE_NUMBER}"


@dataclass
class AgentSpec:
    """Static config for an agent slot in the AGENT_REGISTRY."""
    agent_id: str
    registered_id: str
    system_prompt: str
    description: str = ""


@dataclass
class AgentRunResult:
    """Outcome of a single run_agent_task() call."""
    ok: bool
    agent_id: str
    output: str = ""
    error: Optional[str] = None
    started_at: float = 0.0
    completed_at: float = 0.0
    timed_out: bool = False
    metadata: dict = field(default_factory=dict)


# Default system prompt fallback when an agent class cannot be imported.
_DEFAULT_SYSTEM_PROMPT = (
    "You are a Borina Mesh agent running headless inside a tmux session. "
    "Respond concisely and stop after answering."
)


def _load_system_prompt(registered_id: str, fallback: str = "") -> str:
    """Pull the agent's system_prompt from the registry without circular imports."""
    try:
        from agents.base import registry
        agent = registry.get(registered_id)
        if agent and getattr(agent, "system_prompt", None):
            return agent.system_prompt
    except Exception:
        pass
    return fallback or _DEFAULT_SYSTEM_PROMPT


# Map the short keys named in the spec → real registry IDs in this repo.
# (The repo registers e.g. "ecommerce-scout"; the runner accepts "scout".)
AGENT_REGISTRY: dict[str, AgentSpec] = {
    "trader": AgentSpec(
        agent_id="trader",
        registered_id="trader",
        system_prompt=_load_system_prompt("trader"),
        description="Risk-paranoid trade analysis",
    ),
    "inbox": AgentSpec(
        agent_id="inbox",
        registered_id="inbox-triage",
        system_prompt=_load_system_prompt("inbox-triage"),
        description="Email + Telegram triage",
    ),
    "scout": AgentSpec(
        agent_id="scout",
        registered_id="ecommerce-scout",
        system_prompt=_load_system_prompt("ecommerce-scout"),
        description="Ecommerce product scout",
    ),
    "ceo": AgentSpec(
        agent_id="ceo",
        registered_id="ceo",
        system_prompt=_load_system_prompt("ceo"),
        description="Strategic morning briefing",
    ),
    "polymarket": AgentSpec(
        agent_id="polymarket",
        registered_id="polymarket-intel",
        system_prompt=_load_system_prompt("polymarket-intel"),
        description="Prediction-market intel",
    ),
    "researcher": AgentSpec(
        agent_id="researcher",
        registered_id="researcher",
        system_prompt=_load_system_prompt("researcher"),
        description="Deep research synthesis",
    ),
    "adset": AgentSpec(
        agent_id="adset",
        registered_id="adset-optimizer",
        system_prompt=_load_system_prompt("adset-optimizer"),
        description="Ad rotation + GMC analytics",
    ),
}


def _workdir_for(agent_id: str) -> str:
    """Pane-prefixed workdir under ~/.borina/agents/p{PANE}/{agent_id}/"""
    target = _AGENTS_HOME / agent_id
    target.mkdir(parents=True, exist_ok=True)
    return str(target)


def _resolve_spec(agent_id: str) -> AgentSpec:
    """Look up an AgentSpec; fall back to a synthetic one if the id is registered
    but missing from AGENT_REGISTRY (e.g. a new agent the runner doesn't know yet).
    """
    spec = AGENT_REGISTRY.get(agent_id)
    if spec is not None:
        return spec
    try:
        from agents.base import registry
        if registry.get(agent_id):
            return AgentSpec(
                agent_id=agent_id,
                registered_id=agent_id,
                system_prompt=_load_system_prompt(agent_id),
            )
    except Exception:
        pass
    raise KeyError(
        f"agent {agent_id!r} not found in AGENT_REGISTRY={list(AGENT_REGISTRY)} "
        f"and not registered in agents.base.registry"
    )


def _ensure_session(spec: AgentSpec) -> None:
    sup = get_supervisor()
    if sup.session_exists(spec.agent_id):
        return
    sup.spawn(spec.agent_id, _workdir_for(spec.agent_id), spec.system_prompt)


def _extract_response(transcript: str, prompt: str) -> str:
    """Best-effort: trim the captured pane down to the model's reply.

    The pane shows an interactive Claude UI: header art, the user's typed
    prompt echoed back, then the model's reply, then a fresh `>` prompt.
    We slice from the LAST occurrence of a meaningful prompt fragment,
    drop the echoed user line, and keep everything until the next empty
    input box (`❯ ` followed by no text).
    """
    if not transcript:
        return ""
    # Prefer matching on the longest distinctive substring of the user's prompt.
    needle = prompt.strip().splitlines()[0] if prompt else ""
    needle = needle[:80]
    cut_idx = transcript.rfind(needle) if needle else -1
    body = transcript[cut_idx + len(needle):] if cut_idx != -1 else transcript

    # Lines that are just the divider art or "bypass permissions" footer
    # don't contribute meaningful output — drop them.
    keep: list[str] = []
    for raw_line in body.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            keep.append("")
            continue
        if set(stripped) <= {"─", "-", "═", "_"}:
            continue
        if "bypass permissions on" in stripped:
            continue
        if stripped.startswith("⏵⏵") or stripped.startswith("✻ Baked"):
            continue
        keep.append(line)
    return "\n".join(keep).strip()


async def run_agent_task(
    agent_id: str,
    prompt: str,
    *,
    timeout_seconds: int = 600,
    idle_seconds: int = 4,
    fresh_context: bool = False,
) -> AgentRunResult:
    """Run a prompt against an agent's persistent tmux/claude session.

    On the first call for a given agent we lazily spawn its tmux session.
    `fresh_context=True` kills + respawns the session before sending the
    prompt, which is useful when the agent has accumulated stale context.
    """
    started = time.time()
    spec: Optional[AgentSpec] = None
    try:
        spec = _resolve_spec(agent_id)

        sup = get_supervisor()

        if fresh_context and sup.session_exists(spec.agent_id):
            sup.kill(spec.agent_id)

        _ensure_session(spec)

        # Tmux ops are blocking — push to a worker thread so the event loop stays free.
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, sup.send_prompt, spec.agent_id, prompt)

        timed_out = False
        try:
            final = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    sup.wait_for_idle,
                    spec.agent_id,
                    float(idle_seconds),
                    float(timeout_seconds),
                ),
                timeout=timeout_seconds + 5.0,
            )
        except asyncio.TimeoutError:
            timed_out = True
            final = sup.capture(spec.agent_id, lines=800)

        # The visible pane window is fixed at the terminal's height, so a
        # "diff against baseline" approach falls apart: baseline and final are
        # the same length. Use the prompt text as an anchor instead.
        new_text = _extract_response(final, prompt)

        return AgentRunResult(
            ok=not timed_out,
            agent_id=agent_id,
            output=new_text.strip(),
            error=("timeout" if timed_out else None),
            started_at=started,
            completed_at=time.time(),
            timed_out=timed_out,
            metadata={
                "session_name": f"borina-p{PANE_NUMBER}-{spec.agent_id}",
                "registered_id": spec.registered_id,
                "fresh_context": fresh_context,
            },
        )
    except Exception as e:
        return AgentRunResult(
            ok=False,
            agent_id=agent_id,
            output="",
            error=f"{type(e).__name__}: {e!r} | PATH={os.environ.get('PATH')}",
            started_at=started,
            completed_at=time.time(),
            timed_out=False,
            metadata={
                "session_name": (
                    f"borina-p{PANE_NUMBER}-{spec.agent_id}" if spec else None
                ),
            },
        )
