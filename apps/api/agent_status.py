"""Resolve live agent status from the Job table."""

from sqlmodel import Session, select

from models import Job, JobStatus


def get_agent_status(agent_id: str, engine) -> dict:
    """Return status + current_task for an agent."""
    with Session(engine) as session:
        running = session.exec(
            select(Job)
            .where(Job.agent_id == agent_id, Job.status == JobStatus.RUNNING)
            .order_by(Job.created_at.desc())
            .limit(1)
        ).first()

        if running:
            return {
                "status": "running",
                "current_task": running.prompt[:100],
                "last_run_at": running.started_at.isoformat() if running.started_at else None,
            }

        last_completed = session.exec(
            select(Job)
            .where(Job.agent_id == agent_id, Job.status.in_([JobStatus.COMPLETED, JobStatus.FAILED]))
            .order_by(Job.completed_at.desc())
            .limit(1)
        ).first()

        return {
            "status": "idle",
            "current_task": None,
            "last_run_at": last_completed.completed_at.isoformat() if last_completed and last_completed.completed_at else None,
        }
