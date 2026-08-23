"""Pipeline health tracking — last-run status for the dedicated cron pipelines
that don't go through the generic per-agent scheduler path."""
from datetime import datetime, timedelta

import pipeline_status as ps


def test_record_and_read_back():
    ps.record_pipeline_run("schedule-daily", True, "wrote reports/2026-08-21/daily-brief.md")
    from db import engine
    from models import PipelineRun
    from sqlmodel import Session

    with Session(engine) as s:
        row = s.get(PipelineRun, "schedule-daily")
    assert row is not None
    assert row.last_run_ok is True
    assert row.last_run_at is not None


def test_record_upserts_not_duplicates():
    ps.record_pipeline_run("planner", True, "first")
    ps.record_pipeline_run("planner", False, "second")
    from db import engine
    from models import PipelineRun
    from sqlmodel import Session, select

    with Session(engine) as s:
        rows = s.exec(select(PipelineRun).where(PipelineRun.pipeline_id == "planner")).all()
    assert len(rows) == 1
    assert rows[0].last_run_ok is False
    assert rows[0].last_run_detail == "second"


def test_pipeline_health_flags_never_recorded():
    # A pipeline id that's never had a run recorded is always "stale".
    findings = ps.pipeline_health(now=datetime(2026, 8, 21, 8, 0, 0))
    stale_ids = {f["agent"] for f in findings if f["kind"] == "stale"}
    # At minimum, whichever of PIPELINES no earlier test in this module touched.
    assert stale_ids  # never-recorded or aged-out pipelines are flagged


def test_pipeline_health_flags_stale_run():
    now = datetime(2026, 8, 21, 8, 0, 0)
    old = now - timedelta(hours=40)
    ps.record_pipeline_run("operator-eod", True, "ok")
    from db import engine
    from models import PipelineRun
    from sqlmodel import Session

    with Session(engine) as s:
        row = s.get(PipelineRun, "operator-eod")
        row.last_run_at = old
        s.add(row)
        s.commit()

    findings = ps.pipeline_health(now=now, max_age_hours=36)
    matches = [f for f in findings if f["agent"] == "operator-eod"]
    assert matches and matches[0]["kind"] == "stale"
    assert "40h" in matches[0]["detail"]


def test_pipeline_health_flags_failed_run_within_window():
    now = datetime.utcnow()
    ps.record_pipeline_run("operator-eod-learner", False, "learner produced invalid/empty profile")
    findings = ps.pipeline_health(now=now, max_age_hours=36)
    matches = [f for f in findings if f["agent"] == "operator-eod-learner"]
    assert matches and matches[0]["kind"] == "failing"
    assert matches[0]["severity"] == "warn"


def test_pipeline_health_silent_for_fresh_ok_run():
    now = datetime.utcnow()
    ps.record_pipeline_run("operator-midday", True, "ok")
    findings = ps.pipeline_health(now=now, max_age_hours=36)
    assert not [f for f in findings if f["agent"] == "operator-midday"]
