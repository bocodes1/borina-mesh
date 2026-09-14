"""Reader for an agent's own last saved artifact, so a run can update from
prior state (used by schedule_daily/planner/operator_brain's context packs).

The TASK.md job-contract system that used to live here (a per-agent task spec
file + skip-if-no-signal short-circuit) was removed: it was only wired into
the generic scheduler._run_agent path, which nothing in the live schedule
actually reaches (researcher's own cron was removed, planner/operator run
their own dedicated hardcoded prompts, finance is retired) — dead code that
was also a live footgun, since rescheduling one of those agents via the
Schedules UI would have silently produced a different output format than the
real morning brief/plan/profile."""
from __future__ import annotations


def last_artifact_text(agent_id: str, *, max_chars: int = 1500) -> str:
    """Newest saved artifact body for this agent, cleaned, or ''."""
    try:
        from artifacts import latest_artifact_for_agent  # added in artifacts.py
        body = latest_artifact_for_agent(agent_id) or ""
        return body.strip()[:max_chars]
    except Exception:
        return ""
