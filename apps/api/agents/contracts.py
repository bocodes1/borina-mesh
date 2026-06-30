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


from agents.context_pack import ContextPack


def _signal_path(short_id: str):
    return agent_workdir(short_id) / ".last_signal"


def read_last_signal(short_id: str) -> str:
    try:
        return _signal_path(short_id).read_text().strip()
    except OSError:
        return ""


def write_last_signal(short_id: str, sig: str) -> None:
    try:
        p = _signal_path(short_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(sig)
    except OSError:
        pass


def should_skip(short_id: str, sig: str) -> bool:
    if sig == ContextPack.EMPTY_SIGNAL:
        return True
    return sig == read_last_signal(short_id)
