from sqlmodel import Session, create_engine, SQLModel
from sqlalchemy.pool import StaticPool

from models import Job, JobStatus


def make_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    return engine


def test_stats_empty():
    engine = make_engine()
    from stats_helper import compute_stats
    result = compute_stats(engine)
    assert result["active"] == 0
    assert result["queued"] == 0
    assert result["today"] == 0


def test_stats_with_jobs():
    engine = make_engine()
    with Session(engine) as s:
        s.add(Job(agent_id="ceo", prompt="test", status=JobStatus.RUNNING))
        s.add(Job(agent_id="trader", prompt="test", status=JobStatus.PENDING))
        s.add(Job(agent_id="scout", prompt="test", status=JobStatus.COMPLETED))
        s.commit()

    from stats_helper import compute_stats
    result = compute_stats(engine)
    assert result["active"] == 1
    assert result["queued"] == 1
    assert result["today"] == 3
