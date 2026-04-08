from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from sqlmodel import Session
import agents.ceo  # noqa
import agents.scout  # noqa
import agents.polymarket  # noqa
import agents.researcher  # noqa
import agents.trader  # noqa
import agents.adset  # noqa
import agents.inbox  # noqa
from main import app
from db import engine, init_db
from models import Job, AgentRun, JobStatus

init_db()
client = TestClient(app)


def _seed():
    with Session(engine) as s:
        for i in range(3):
            job = Job(agent_id="ceo", prompt=f"p{i}", status=JobStatus.COMPLETED)
            s.add(job)
            s.commit()
            s.refresh(job)
            s.add(AgentRun(job_id=job.id, agent_id="ceo", output="ok", tokens_used=500, cost_usd=0.005))
        s.commit()


def test_analytics_summary():
    _seed()
    response = client.get("/analytics/summary")
    assert response.status_code == 200
    data = response.json()
    assert "total_runs" in data
    assert "total_tokens" in data
    assert "total_cost_usd" in data
    assert "runs_by_agent" in data
    assert data["total_runs"] >= 3


def test_analytics_timeseries():
    response = client.get("/analytics/timeseries?days=7")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    if data:
        first = data[0]
        assert "date" in first
        assert "runs" in first
        assert "tokens" in first
