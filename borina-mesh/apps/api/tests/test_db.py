import pytest
from datetime import datetime
from sqlmodel import Session, create_engine, SQLModel
from models import Job, AgentRun, JobStatus


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(eng)
    return eng


def test_create_job(engine):
    with Session(engine) as s:
        job = Job(
            agent_id="ceo",
            prompt="Summarize today",
            status=JobStatus.PENDING,
        )
        s.add(job)
        s.commit()
        s.refresh(job)
        assert job.id is not None
        assert job.created_at is not None
        assert job.status == JobStatus.PENDING


def test_create_agent_run(engine):
    with Session(engine) as s:
        job = Job(agent_id="scout", prompt="find products", status=JobStatus.PENDING)
        s.add(job)
        s.commit()
        s.refresh(job)

        run = AgentRun(
            job_id=job.id,
            agent_id="scout",
            output="Found 5 products",
            tokens_used=1200,
            cost_usd=0.012,
        )
        s.add(run)
        s.commit()
        s.refresh(run)
        assert run.id is not None
        assert run.job_id == job.id
