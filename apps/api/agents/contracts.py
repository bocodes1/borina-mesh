"""Per-agent job contracts: a TASK.md (the concrete recurring job + output
format) living in the agent's fixed workdir, plus a reader for the agent's own
last artifact so a run can update from prior state."""
from __future__ import annotations

from pathlib import Path

CONTRACTED: set[str] = {"researcher", "planner", "operator", "finance"}


def agent_workdir(short_id: str) -> Path:
    from dispatch.answer import _agent_workdir
    return _agent_workdir(short_id)


def load_task_spec(short_id: str) -> str | None:
    try:
        p = agent_workdir(short_id) / "TASK.md"
        if p.is_file():
            txt = p.read_text().strip()
            return txt or None
    except OSError:
        pass
    return None


def last_artifact_text(agent_id: str, *, max_chars: int = 1500) -> str:
    """Newest saved artifact body for this agent, cleaned, or ''."""
    try:
        from artifacts import latest_artifact_for_agent  # added in artifacts.py
        body = latest_artifact_for_agent(agent_id) or ""
        return body.strip()[:max_chars]
    except Exception:
        return ""
