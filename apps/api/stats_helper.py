"""Job statistics helpers."""

from datetime import datetime
from sqlmodel import Session, select, func

from models import Job, JobStatus


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
