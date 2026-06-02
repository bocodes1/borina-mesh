"""Tasks CRUD + /daily/summary (spec §5)."""
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_tasks_crud_roundtrip():
    # create
    r = client.post("/tasks", json={"title": "Ship rebuild", "tag": "borina", "priority": "high"})
    assert r.status_code == 201, r.text
    task = r.json()
    tid = task["id"]
    assert task["title"] == "Ship rebuild" and task["done"] is False

    # list includes it
    r = client.get("/tasks")
    assert r.status_code == 200
    assert any(t["id"] == tid for t in r.json())

    # patch → mark done
    r = client.patch(f"/tasks/{tid}", json={"done": True})
    assert r.status_code == 200 and r.json()["done"] is True

    # filter by done
    r = client.get("/tasks", params={"done": True})
    assert any(t["id"] == tid for t in r.json())

    # delete
    assert client.delete(f"/tasks/{tid}").status_code == 204
    assert all(t["id"] != tid for t in client.get("/tasks").json())


def test_task_invalid_tag_rejected():
    r = client.post("/tasks", json={"title": "x", "tag": "not-a-tag"})
    assert r.status_code == 422


def test_task_invalid_priority_rejected():
    r = client.post("/tasks", json={"title": "x", "priority": "urgent"})
    assert r.status_code == 422


def test_patch_missing_task_404():
    assert client.patch("/tasks/999999", json={"done": True}).status_code == 404


def test_daily_summary_shape():
    r = client.get("/daily/summary")
    assert r.status_code == 200
    data = r.json()
    assert set(["date", "has_brief", "brief", "weather", "open_tasks"]).issubset(data)
    # weather not configured in tests → graceful not-connected envelope
    assert data["weather"]["connected"] is False
    # brief sections present as keys (values may be null when no brief written)
    assert "tldr" in data["brief"] and "tasks_focus" in data["brief"]
