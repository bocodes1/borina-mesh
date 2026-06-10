"""Startup orphan recovery for non-telegram jobs (Phase 4 §4).

The scheduler creates jobs in RUNNING; a restart strands them, inflating the
status bar's RUNNING count forever (84 stale rows observed live). On startup
they are failed; telegram_dispatch RUNNING jobs are left for the dispatch
worker, which re-queues (not fails) them.
"""
from sqlmodel import Session, select

from db import engine
from models import Job, JobStatus
from stats_helper import fail_orphaned_running_jobs


def _mk(session, kind, status=JobStatus.RUNNING):
    job = Job(agent_id="trader", prompt="[scheduled] x", status=status, kind=kind)
    session.add(job)
    session.commit()
    session.refresh(job)
    return job.id


def test_orphaned_running_jobs_failed_telegram_left_alone():
    with Session(engine) as s:
        stale_id = _mk(s, kind=None)
        sched_id = _mk(s, kind="scheduled")
        tg_id = _mk(s, kind="telegram_dispatch")
        done_id = _mk(s, kind=None, status=JobStatus.COMPLETED)

    n = fail_orphaned_running_jobs(engine)
    assert n >= 2  # at least our two non-telegram running rows

    with Session(engine) as s:
        assert s.get(Job, stale_id).status == JobStatus.FAILED
        assert s.get(Job, stale_id).error == "orphaned by service restart"
        assert s.get(Job, sched_id).status == JobStatus.FAILED
        assert s.get(Job, tg_id).status == JobStatus.RUNNING  # worker's job
        assert s.get(Job, done_id).status == JobStatus.COMPLETED
        # cleanup
        for jid in (stale_id, sched_id, tg_id, done_id):
            s.delete(s.get(Job, jid))
        s.commit()
