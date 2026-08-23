"""Pipeline health tracking (Phase A) — last-run status for the dedicated
cron pipelines that don't go through the generic per-agent scheduler path:
schedule-daily (6am brief), planner (6:30am plan), operator-midday,
operator-eod, and operator-eod-learner (the nightly operator_brain profile
rewrite specifically — its own signal, since it can silently no-op without
`run_phase("eod")` itself raising).

This exists because none of those pipelines wrote any execution record before
now, so nothing could detect staleness — which is exactly how the nightly
learner ran silently broken for 27+ days (see operator_brain.py __call_agent__
history). Deliberately not folded into AgentConfig/the fleet roster — see
models.PipelineRun.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

PIPELINES = (
    "schedule-daily",
    "planner",
    "operator-midday",
    "operator-eod",
    "operator-eod-learner",
)
MAX_AGE_HOURS = 36


def record_pipeline_run(pipeline_id: str, ok: bool, detail: str = "") -> None:
    from db import engine
    from models import PipelineRun
    from sqlmodel import Session

    with Session(engine) as s:
        row = s.get(PipelineRun, pipeline_id)
        if row is None:
            row = PipelineRun(pipeline_id=pipeline_id)
        row.last_run_at = datetime.utcnow()
        row.last_run_ok = ok
        row.last_run_detail = (detail or "")[:200]
        s.add(row)
        s.commit()


def pipeline_health(*, now: Optional[datetime] = None, max_age_hours: int = MAX_AGE_HOURS) -> list[dict]:
    """Findings for any tracked pipeline that hasn't run recently, or whose
    last recorded run failed. Same {kind, agent, severity, detail} shape as
    fleet/health.py's findings so fleet.cards.health_card can render both."""
    from db import engine
    from models import PipelineRun
    from sqlmodel import Session, select

    now = now or datetime.utcnow()
    cutoff = now - timedelta(hours=max_age_hours)
    with Session(engine) as s:
        rows = {r.pipeline_id: r for r in s.exec(select(PipelineRun)).all()}

    findings = []
    for pid in PIPELINES:
        row = rows.get(pid)
        if row is None or row.last_run_at is None:
            findings.append({"kind": "stale", "agent": pid, "severity": "alert",
                              "detail": "never recorded a run"})
        elif row.last_run_at < cutoff:
            age_h = int((now - row.last_run_at).total_seconds() // 3600)
            findings.append({"kind": "stale", "agent": pid, "severity": "alert",
                              "detail": f"no run in {age_h}h"})
        elif row.last_run_ok is False:
            findings.append({"kind": "failing", "agent": pid, "severity": "warn",
                              "detail": row.last_run_detail or "last run failed"})
    return findings
