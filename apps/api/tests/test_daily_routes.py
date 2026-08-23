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
    assert r.json()["completed_at"] is not None  # Phase D1: completion is timestamped

    # filter by done
    r = client.get("/tasks", params={"done": True})
    assert any(t["id"] == tid for t in r.json())

    # delete
    assert client.delete(f"/tasks/{tid}").status_code == 204
    assert all(t["id"] != tid for t in client.get("/tasks").json())


def test_task_uncomplete_clears_completed_at():
    r = client.post("/tasks", json={"title": "toggle me"})
    tid = r.json()["id"]
    client.patch(f"/tasks/{tid}", json={"done": True})
    r = client.patch(f"/tasks/{tid}", json={"done": False})
    assert r.status_code == 200
    assert r.json()["done"] is False and r.json()["completed_at"] is None
    client.delete(f"/tasks/{tid}")


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


def test_correction_reaches_the_learner_signal():
    """Phase D2: a correction posted from /daily flows through the
    conversation log (role=correction) into the same {conversation} signal
    the nightly learner reads — no separate storage/plumbing."""
    from datetime import date
    import conversation_log as cl

    r = client.post("/daily/correction", json={"text": "Actually the launch slipped to Friday."})
    assert r.status_code == 201
    convo = cl.recent_for_day(date.today().isoformat())
    assert any(m["role"] == "correction" and "slipped to Friday" in m["text"] for m in convo)


def test_correction_rejects_empty_text():
    assert client.post("/daily/correction", json={"text": "   "}).status_code == 422
