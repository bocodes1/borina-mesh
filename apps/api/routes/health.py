"""Pipeline health surface (Phase A) — last-run status for the dedicated cron
pipelines, so staleness like the operator_brain nightly-learner bug (silently
stopped writing for 27+ days, nothing surfaced it) can't go unnoticed again.
"""
from fastapi import APIRouter
from sqlmodel import Session, select

from db import get_session, engine
from models import PipelineRun
from pipeline_status import PIPELINES, MAX_AGE_HOURS, pipeline_health

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/pipelines")
async def get_pipeline_health():
    """Last-run timestamp/status for every tracked pipeline, plus any current
    staleness/failure findings."""
    with Session(engine) as s:
        rows = {r.pipeline_id: r for r in s.exec(select(PipelineRun)).all()}
    pipelines = [
        {
            "pipeline_id": pid,
            "last_run_at": rows[pid].last_run_at if pid in rows else None,
            "last_run_ok": rows[pid].last_run_ok if pid in rows else None,
            "last_run_detail": rows[pid].last_run_detail if pid in rows else None,
        }
        for pid in PIPELINES
    ]
    return {
        "pipelines": pipelines,
        "findings": pipeline_health(),
        "max_age_hours": MAX_AGE_HOURS,
    }
