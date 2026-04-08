from fastapi.testclient import TestClient
import agents.ceo  # noqa - triggers registration
import agents.scout  # noqa
import agents.polymarket  # noqa
from main import app
from db import init_db


init_db()
client = TestClient(app)


def test_list_agents():
    response = client.get("/agents")
    assert response.status_code == 200
    agents = response.json()
    assert isinstance(agents, list)
    agent_ids = [a["id"] for a in agents]
    assert "ceo" in agent_ids
    assert "ecommerce-scout" in agent_ids
    assert "polymarket-intel" in agent_ids


def test_get_agent_by_id():
    response = client.get("/agents/ceo")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "ceo"
    assert data["name"] == "CEO"
    assert "system_prompt" not in data  # don't expose prompts


def test_get_agent_not_found():
    response = client.get("/agents/nonexistent")
    assert response.status_code == 404


def test_create_job():
    response = client.post("/jobs", json={"agent_id": "ceo", "prompt": "test"})
    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert data["agent_id"] == "ceo"
    assert data["status"] == "pending"


def test_create_job_invalid_agent():
    response = client.post("/jobs", json={"agent_id": "fake", "prompt": "test"})
    assert response.status_code == 404


def test_list_jobs():
    response = client.get("/jobs")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
