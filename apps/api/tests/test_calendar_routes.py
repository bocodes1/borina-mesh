"""Calendar read + user-initiated create gate (spec §6)."""
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_list_events_shape_when_unconnected():
    r = client.get("/calendar/events", params={"from": "2026-06-01T00:00:00Z", "to": "2026-06-30T00:00:00Z"})
    assert r.status_code == 200
    data = r.json()
    assert "calendar" in data and "events" in data and "task_chips" in data
    # Google not authorized in tests → not connected, empty events, no crash.
    assert data["calendar"]["connected"] is False
    assert data["events"] == []


def test_create_event_rejected_without_user_action():
    r = client.post(
        "/calendar/events",
        json={"summary": "Auto event", "start": "2026-06-02T09:00:00Z", "end": "2026-06-02T09:30:00Z"},
    )
    # user_initiated defaults to False → hard 403, nothing created.
    assert r.status_code == 403
    assert "explicit user action" in r.text


def test_create_event_user_initiated_but_unauthorized():
    r = client.post(
        "/calendar/events",
        json={
            "summary": "Real click",
            "start": "2026-06-02T09:00:00Z",
            "end": "2026-06-02T09:30:00Z",
            "user_initiated": True,
        },
    )
    # Passes the gate, but Google isn't authorized in tests → graceful not-connected.
    assert r.status_code == 201
    body = r.json()
    assert body["connected"] is False
    assert "not authorized" in (body["error"] or "")


def test_create_event_missing_fields_422():
    r = client.post("/calendar/events", json={"summary": "no times", "user_initiated": True})
    assert r.status_code == 422


def test_task_chips_reflect_due_tasks():
    # A task with a due date inside the window should appear as an all-day chip.
    client.post(
        "/tasks",
        json={"title": "Quarterly review", "tag": "work", "due": "2026-06-15T12:00:00"},
    )
    r = client.get("/calendar/events", params={"from": "2026-06-01T00:00:00", "to": "2026-06-30T00:00:00"})
    chips = r.json()["task_chips"]
    assert any(c["kind"] == "task" and "Quarterly review" in c["title"] for c in chips)


def test_task_chips_window_compares_instants_not_iso_strings():
    """The window must be parsed as datetimes. A due exactly at the lower bound
    ("...00:00:00") is lexicographically *less* than the frontend's
    "...00:00:00.000Z" bound (so raw-string `<=` wrongly excludes it), yet it's
    the same instant — datetime comparison must include it."""
    client.post(
        "/tasks",
        json={"title": "Boundary task", "tag": "work", "due": "2026-07-10T00:00:00"},
    )
    # Window uses 'Z' / millisecond precision like the frontend's toISOString().
    r = client.get(
        "/calendar/events",
        params={"from": "2026-07-10T00:00:00.000Z", "to": "2026-07-11T00:00:00.000Z"},
    )
    chips = r.json()["task_chips"]
    assert any("Boundary task" in c["title"] for c in chips)
