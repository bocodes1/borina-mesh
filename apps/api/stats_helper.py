"""Job statistics helpers."""

import os
from datetime import datetime
from sqlmodel import Session, select, func, or_

from models import Job, JobStatus


def fail_orphaned_running_jobs(engine) -> int:
    """Mark non-telegram jobs left RUNNING by a crash/restart as failed, so the
    status bar's RUNNING count reflects reality (84 stale rows observed live on
    2026-06-09). telegram_dispatch jobs are excluded — dispatch.worker
    re-queues those on startup."""
    with Session(engine) as session:
        orphans = session.exec(
            select(Job).where(
                Job.status == JobStatus.RUNNING,
                or_(Job.kind == None, Job.kind != "telegram_dispatch"),  # noqa: E711
            )
        ).all()
        failed = 0
        for job in orphans:
            # Builders run detached and SURVIVE API restarts — spare them
            # while their pid is alive.
            if job.kind == "builder" and job.worker_pid and _pid_alive(job.worker_pid):
                continue
            job.status = JobStatus.FAILED
            job.completed_at = datetime.utcnow()
            job.error = "orphaned by service restart"
            session.add(job)
            failed += 1
        session.commit()
        return failed


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def compute_stats(engine) -> dict:
    """Compute active, queued, and today job counts."""
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    with Session(engine) as session:
        active = session.exec(
            select(func.count()).select_from(Job).where(Job.status == JobStatus.RUNNING)
        ).one()
        queued = session.exec(
            select(func.count()).select_from(Job).where(Job.status == JobStatus.PENDING)
        ).one()
        today = session.exec(
            select(func.count()).select_from(Job).where(Job.created_at >= today_start)
        ).one()

    return {"active": active, "queued": queued, "today": today}
