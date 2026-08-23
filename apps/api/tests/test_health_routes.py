"""GET /health/pipelines — pipeline last-run status surface."""
from fastapi.testclient import TestClient

from main import app
import pipeline_status as ps

client = TestClient(app)


def test_get_pipeline_health_shape():
    ps.record_pipeline_run("schedule-daily", True, "wrote a brief")
    r = client.get("/health/pipelines")
    assert r.status_code == 200
    body = r.json()
    assert "pipelines" in body and "findings" in body and "max_age_hours" in body
    ids = {p["pipeline_id"] for p in body["pipelines"]}
    assert set(ps.PIPELINES) == ids
    sd = next(p for p in body["pipelines"] if p["pipeline_id"] == "schedule-daily")
    assert sd["last_run_ok"] is True
