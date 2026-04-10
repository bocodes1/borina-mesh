from datetime import datetime
from sqlmodel import Session, create_engine, SQLModel

from models import MorningBrief


def make_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def test_morning_brief_model():
    engine = make_engine()
    with Session(engine) as s:
        brief = MorningBrief(
            date="2026-04-09",
            summary="Test brief",
            cost_summary='{"ceo": 0.05}',
            total_runs=3,
            total_cost_usd=0.05,
        )
        s.add(brief)
        s.commit()
        s.refresh(brief)
        assert brief.id is not None
        assert brief.date == "2026-04-09"
        assert brief.summary == "Test brief"
        assert brief.total_runs == 3


def test_morning_brief_date_unique():
    import pytest
    from sqlalchemy.exc import IntegrityError

    engine = make_engine()
    with Session(engine) as s:
        s.add(MorningBrief(date="2026-04-09", summary="first"))
        s.commit()
    with Session(engine) as s:
        s.add(MorningBrief(date="2026-04-09", summary="second"))
        with pytest.raises(IntegrityError):
            s.commit()


from models import AgentRun, Job, JobStatus


def test_gather_last_24h_runs():
    from briefs import gather_last_24h_runs

    engine = make_engine()
    with Session(engine) as s:
        job = Job(agent_id="ceo", prompt="test", status=JobStatus.COMPLETED)
        s.add(job)
        s.commit()
        s.refresh(job)
        run = AgentRun(job_id=job.id, agent_id="ceo", output="found 3 products")
        s.add(run)
        s.commit()

    runs = gather_last_24h_runs(engine)
    assert len(runs) == 1
    assert runs[0].agent_id == "ceo"


def test_build_brief_prompt_with_runs():
    from briefs import build_brief_prompt

    runs = [
        AgentRun(id=1, job_id=1, agent_id="ceo", output="morning report done"),
        AgentRun(id=2, job_id=2, agent_id="trader", output="bot healthy"),
    ]
    prompt = build_brief_prompt(runs)
    assert "ceo" in prompt
    assert "trader" in prompt
    assert "morning report done" in prompt


def test_build_brief_prompt_empty():
    from briefs import build_brief_prompt

    prompt = build_brief_prompt([])
    assert "No agent runs" in prompt


import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine


@pytest.fixture
def client():
    """TestClient with in-memory DB."""
    from db import get_session
    from main import app

    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(test_engine)

    def _override_session():
        with Session(test_engine) as session:
            yield session

    app.dependency_overrides[get_session] = _override_session
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_get_briefs_empty(client):
    resp = client.get("/briefs")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_briefs_latest_empty(client):
    resp = client.get("/briefs/latest")
    assert resp.status_code == 404
