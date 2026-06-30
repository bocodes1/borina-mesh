"""Planner agent — staged proposals, approve-commits-only (Phase 3 §3).

The safety-critical guarantee: the planner NEVER writes the calendar on its own.
Only an explicit approve triggers exactly one user-initiated write.
"""
import pytest
from fastapi.testclient import TestClient

from main import app
from integrations import google_calendar
from integrations.base import ok
from db import session_scope
from models import PlanItem, Task
import planner

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    # Fresh plan/task tables each test.
    from sqlmodel import select
    with session_scope() as s:
        for it in s.exec(select(PlanItem)).all():
            s.delete(it)
        for t in s.exec(select(Task)).all():
            s.delete(t)
        s.commit()
    yield


def _spy_create_event(monkeypatch):
    calls = []

    def fake(event, *, user_initiated=False, calendar_id="primary"):
        calls.append({"user_initiated": user_initiated, "event": event})
        return ok("google_calendar", {"id": "evt_123"})

    monkeypatch.setattr(google_calendar, "create_event", fake)
    return calls


def test_planner_agent_prompt_includes_context_block(monkeypatch, tmp_path):
    """The live planner draft prompt is grounded in the same context pack
    (vault recall + last artifact) as the other bespoke morning agents."""
    import asyncio
    import agents.context_pack as CP
    from agents import runner_v2

    monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
    monkeypatch.setattr(CP, "build_context_pack",
                        lambda aid, **k: CP.ContextPack(text="VAULT+PLAN", signal_hash="x"))
    captured = {}

    async def _fake_run(agent_id, prompt, **k):
        captured["prompt"] = prompt

        class R:
            output = ""

        return R()

    monkeypatch.setattr(runner_v2, "run_agent_task", _fake_run)
    asyncio.run(planner.generate_plan_with_agent(day="2026-06-18"))
    assert "VAULT+PLAN" in captured["prompt"]
    assert "CONTEXT:" in captured["prompt"]


def test_generate_plan_writes_no_calendar(monkeypatch):
    calls = _spy_create_event(monkeypatch)
    summary = planner.generate_plan()
    # proposals exist...
    assert summary["task_count"] >= 1 and summary["calendar_count"] >= 1
    # ...but the calendar was NEVER written.
    assert calls == []
    plan = planner.get_plan()
    assert plan["has_plan"] is True
    assert all(i["status"] == "proposed" for i in plan["items"])


def test_no_autonomous_write_regression(monkeypatch):
    """Explicit guard: generating a plan must never call create_event."""
    calls = _spy_create_event(monkeypatch)
    planner.generate_plan()
    planner.generate_plan()  # regenerate too
    assert calls == [], "planner must never auto-write the calendar"


def test_unapproved_proposal_commits_nothing(monkeypatch):
    calls = _spy_create_event(monkeypatch)
    planner.generate_plan()
    # No tasks created from proposed task-items, no calendar writes.
    with session_scope() as s:
        from sqlmodel import select
        assert s.exec(select(Task)).all() == []
    assert calls == []


def test_approve_calendar_item_triggers_one_user_initiated_write(monkeypatch):
    calls = _spy_create_event(monkeypatch)
    planner.generate_plan()
    plan = planner.get_plan()
    cal_item = next(i for i in plan["items"] if i["kind"] == "calendar")

    r = client.post(f"/daily/plan/{cal_item['id']}/approve")
    assert r.status_code == 200 and r.json()["status"] == "approved"
    # exactly one write, and it was user-initiated
    assert len(calls) == 1 and calls[0]["user_initiated"] is True

    # idempotent: approving again does not write a second time
    r2 = client.post(f"/daily/plan/{cal_item['id']}/approve")
    assert r2.json().get("already_decided") is True
    assert len(calls) == 1


def test_approve_calendar_item_while_disconnected_stays_proposed(monkeypatch):
    """If the calendar write doesn't commit (not connected), the item must stay
    'proposed' so it can be approved again later — never silently lost."""
    from integrations.base import not_connected

    def fake(event, *, user_initiated=False, calendar_id="primary"):
        return not_connected("google_calendar", "Google Calendar not authorized")

    monkeypatch.setattr(google_calendar, "create_event", fake)
    planner.generate_plan()
    plan = planner.get_plan()
    cal_item = next(i for i in plan["items"] if i["kind"] == "calendar")

    res = planner.approve_item(cal_item["id"])
    assert res["committed"] is False
    # still proposed → retryable
    with session_scope() as s:
        item = s.get(PlanItem, cal_item["id"])
        assert item.status == "proposed"

    # once connected, a re-approve commits the write
    calls = _spy_create_event(monkeypatch)
    res2 = planner.approve_item(cal_item["id"])
    assert res2["committed"] is True
    assert len(calls) == 1
    with session_scope() as s:
        assert s.get(PlanItem, cal_item["id"]).status == "approved"


def test_approve_task_item_creates_task(monkeypatch):
    _spy_create_event(monkeypatch)
    planner.generate_plan()
    plan = planner.get_plan()
    task_item = next(i for i in plan["items"] if i["kind"] == "task")

    r = client.post(f"/daily/plan/{task_item['id']}/approve")
    assert r.status_code == 200 and r.json()["status"] == "approved"
    with session_scope() as s:
        from sqlmodel import select
        tasks = s.exec(select(Task)).all()
    assert len(tasks) == 1


def test_reject_commits_nothing(monkeypatch):
    calls = _spy_create_event(monkeypatch)
    planner.generate_plan()
    plan = planner.get_plan()
    item = plan["items"][0]

    r = client.post(f"/daily/plan/{item['id']}/reject")
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert calls == []
    with session_scope() as s:
        from sqlmodel import select
        assert s.exec(select(Task)).all() == []


def test_plan_endpoint_shape():
    planner.generate_plan()
    data = client.get("/daily/plan").json()
    assert set(["day", "has_plan", "items", "tasks", "calendar"]).issubset(data)
    assert data["has_plan"] is True


def test_telegram_callback_security_and_approve(monkeypatch):
    from dispatch import dispatcher
    monkeypatch.setattr(dispatcher, "send_telegram_message", lambda *a, **k: None)
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "sek")
    BO = 6452258223
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", str(BO))
    _spy_create_event(monkeypatch)
    planner.generate_plan()
    item = next(i for i in planner.get_plan()["items"] if i["kind"] == "task")
    H = {"X-Telegram-Bot-Api-Secret-Token": "sek"}

    # non-allowed sender → ignored, item stays proposed (security boundary)
    r = client.post("/api/telegram/webhook", headers=H,
                    json={"callback_query": {"from": {"id": 999}, "data": f"approve:{item['id']}"}})
    assert r.json()["status"] == "ignored"
    assert next(i for i in planner.get_plan()["items"] if i["id"] == item["id"])["status"] == "proposed"

    # allowed sender → approved
    r = client.post("/api/telegram/webhook", headers=H,
                    json={"callback_query": {"from": {"id": BO}, "data": f"approve:{item['id']}"}})
    assert r.json()["status"] == "approve"
    assert next(i for i in planner.get_plan()["items"] if i["id"] == item["id"])["status"] == "approved"


def test_telegram_callback_approve_disconnected_reports_pending(monkeypatch):
    from dispatch import dispatcher
    from integrations.base import not_connected
    sent = []
    monkeypatch.setattr(dispatcher, "send_telegram_message", lambda chat, msg, **k: sent.append(msg))
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "sek")
    BO = 6452258223
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", str(BO))
    monkeypatch.setattr(
        google_calendar, "create_event",
        lambda event, **k: not_connected("google_calendar", "Google Calendar not authorized"),
    )
    planner.generate_plan()
    item = next(i for i in planner.get_plan()["items"] if i["kind"] == "calendar")
    H = {"X-Telegram-Bot-Api-Secret-Token": "sek"}

    client.post("/api/telegram/webhook", headers=H,
                json={"callback_query": {"from": {"id": BO}, "data": f"approve:{item['id']}"}})
    # item is still pending, and the reply says so (not "Approved")
    assert next(i for i in planner.get_plan()["items"] if i["id"] == item["id"])["status"] == "proposed"
    assert sent and "pending" in sent[0].lower() and "approved" not in sent[0].lower()
