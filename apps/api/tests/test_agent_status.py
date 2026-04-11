from datetime import datetime
from sqlmodel import Session, create_engine, SQLModel
from sqlalchemy.pool import StaticPool

from models import Job, JobStatus


def make_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    return engine


def test_agent_status_running():
    from agent_status import get_agent_status
    engine = make_engine()
    with Session(engine) as s:
        s.add(Job(agent_id="ceo", prompt="briefing", status=JobStatus.RUNNING, started_at=datetime.utcnow()))
        s.commit()

    status = get_agent_status("ceo", engine)
    assert status["status"] == "running"
    assert "briefing" in status["current_task"]


def test_agent_status_idle():
    from agent_status import get_agent_status
    engine = make_engine()
    status = get_agent_status("ceo", engine)
    assert status["status"] == "idle"
    assert status["current_task"] is None
