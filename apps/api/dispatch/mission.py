"""Mission pipeline (§C): one Telegram prompt → CEO decomposes into ≤4
read-only subtasks → agents run in parallel (separate tmux sessions) → CEO
synthesizes one report.

Safety: subtask agents are restricted to MISSION_AGENTS (read-only intel
roster — no planner, no write paths); the forbidden gate already refused
action-shaped missions upstream. Every stage degrades: decompose failure →
single researcher subtask; synthesis failure → deterministic section join.
JSON from a tmux pane needs the newline-collapse repair (pane wrap breaks
string literals — hit live 2026-06-09).
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Callable, Optional

MISSION_AGENTS = {"researcher", "trader", "polymarket", "finance", "scout", "inbox", "adset"}
MAX_SUBTASKS = 4
_RESULT_CAP = 4000  # chars of each subtask result fed to synthesis

DECOMPOSE_PROMPT = """Decompose this mission into 2-{max_subtasks} independent READ-ONLY subtasks.
Mission: {mission}

Available agents: {agents}.
Output ONLY a JSON array (no prose, no code fences):
  [{{"agent": "<agent>", "prompt": "<specific subtask>"}}]
Pick only agents that genuinely add signal for THIS mission."""

SYNTH_PROMPT = """Synthesize ONE markdown mission report from your agents' findings.
Mission: {mission}

{sections}

The FIRST line must be a one-sentence plain summary (it becomes the chat reply).
Lead with the answer, reconcile disagreements explicitly, no filler. No emojis."""


async def run_agent(agent_id: str, prompt: str) -> str:
    from agents.runner_v2 import run_agent_task
    from dispatch.answer import clean_agent_output

    result = await run_agent_task(agent_id, prompt)
    # Strip tmux/TUI chrome so mission sections + synthesis aren't pane garbage.
    return clean_agent_output(getattr(result, "output", None) or "")


def _parse_subtasks(text: str) -> Optional[list[dict]]:
    if not text:
        return None
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        return None
    try:
        raw = json.loads(m.group(0))
    except Exception:
        try:
            raw = json.loads(re.sub(r"\n\s*", " ", m.group(0)))
        except Exception:
            return None
    if not isinstance(raw, list):
        return None
    subs = []
    for it in raw:
        if not isinstance(it, dict):
            continue
        agent = it.get("agent")
        prompt = str(it.get("prompt") or "").strip()
        if agent in MISSION_AGENTS and prompt:
            subs.append({"agent": agent, "prompt": prompt})
    return subs[:MAX_SUBTASKS] or None


async def run_mission(
    mission_text: str, progress: Optional[Callable[[str], None]] = None
) -> str:
    """Returns the final mission report markdown. Never raises on stage
    failures — degrades instead (this feeds a Telegram reply)."""
    agents_list = ", ".join(sorted(MISSION_AGENTS))
    decompose = await run_agent(
        "ceo",
        DECOMPOSE_PROMPT.format(
            max_subtasks=MAX_SUBTASKS, mission=mission_text, agents=agents_list
        ),
    )
    subtasks = _parse_subtasks(decompose) or [
        {"agent": "researcher", "prompt": mission_text}
    ]
    if progress:
        try:
            progress(
                f"Mission: {len(subtasks)} agent(s) dispatched - "
                + ", ".join(s["agent"] for s in subtasks)
            )
        except Exception:  # noqa: BLE001
            pass

    subtask_preamble = (
        "Mission subtask (read-only intel only - never place orders, transfer "
        "funds, send messages, or modify anything): "
    )
    results = await asyncio.gather(
        *(run_agent(s["agent"], subtask_preamble + s["prompt"]) for s in subtasks),
        return_exceptions=True,
    )

    sections = []
    for sub, res in zip(subtasks, results):
        body = res if isinstance(res, str) else f"(failed: {res})"
        body = (body or "(no output)").strip()[:_RESULT_CAP]
        sections.append(f"## {sub['agent']} — {sub['prompt'][:80]}\n\n{body}")

    synthesis = await run_agent(
        "ceo", SYNTH_PROMPT.format(mission=mission_text, sections="\n\n".join(sections))
    )
    if synthesis.strip():
        return synthesis
    # Deterministic fallback: the raw sections are still a useful report.
    return f"# Mission report: {mission_text[:80]}\n\n" + "\n\n".join(sections)
