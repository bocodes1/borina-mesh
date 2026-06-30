"""L2 daily operator — calendar write gates, freebusy, phases, approval card."""
from datetime import datetime

import pytest

from integrations import google_calendar as gc
from integrations.base import not_connected, ok
from freebusy import find_gaps


# ── calendar write helpers are HARD-gated on user_initiated ─────────────────────
def test_move_update_delete_refuse_without_user_action():
    assert gc.move_event("e1", "2026-06-18T10:00:00", "2026-06-18T11:00:00").connected is False
    assert gc.update_event("e1", {"summary": "x"}).connected is False
    assert gc.delete_event("e1").connected is False


def test_writes_succeed_with_user_action(monkeypatch):
    monkeypatch.setattr(gc, "_oauth_configured", lambda: True)
    monkeypatch.setattr(gc, "_access_token", lambda: "tok")
    monkeypatch.setattr(gc, "http_patch_json", lambda *a, **k: {"id": "e1", "htmlLink": "h"})
    monkeypatch.setattr(gc, "http_delete", lambda *a, **k: 204)
    assert gc.move_event("e1", "2026-06-18T10:00:00", "2026-06-18T11:00:00", user_initiated=True).connected
    assert gc.update_event("e1", {"summary": "x"}, user_initiated=True).connected
    d = gc.delete_event("e1", user_initiated=True)
    assert d.connected and d.data["deleted"] is True


# ── freebusy gap-finding ───────────────────────────────────────────────────────
def test_find_gaps_empty_calendar_returns_window_start():
    day = datetime(2026, 6, 18, 0, 0)
    gap = find_gaps([], day=day, min_minutes=120, work_start=9, work_end=18)
    assert gap and gap["start"].endswith("09:00:00") or "T09:00" in gap["start"]


def test_find_gaps_finds_slot_after_busy_block():
    day = datetime(2026, 6, 18, 0, 0)
    busy = [{"start": "2026-06-18T09:00:00", "end": "2026-06-18T10:30:00"}]
    gap = find_gaps(busy, day=day, min_minutes=120, work_start=9, work_end=18)
    assert "T10:30" in gap["start"]            # first ≥120min gap after the block


def test_find_gaps_none_when_packed():
    day = datetime(2026, 6, 18, 0, 0)
    busy = [{"start": "2026-06-18T09:00:00", "end": "2026-06-18T18:00:00"}]
    assert find_gaps(busy, day=day, min_minutes=120, work_start=9, work_end=18) is None


# ── approve_item dispatches calendar ops through the user gate ──────────────────
def test_approve_item_dispatches_move(monkeypatch):
    import planner
    from db import session_scope
    from models import PlanItem
    import json

    calls = {}
    def fake_move(event_id, start, end, *, user_initiated=False, calendar_id="primary"):
        calls["move"] = (event_id, start, end, user_initiated)
        return ok("google_calendar", {"id": "e9"})
    # planner imports google_calendar lazily inside approve_item.
    from integrations import google_calendar
    monkeypatch.setattr(google_calendar, "move_event", fake_move)

    with session_scope() as s:
        item = PlanItem(day="2026-06-18", kind="calendar", title="move standup",
                        payload_json=json.dumps({"op": "move", "event_id": "e9",
                                                 "start": "2026-06-18T10:00:00", "end": "2026-06-18T10:30:00"}))
        s.add(item)
        s.commit()
        s.refresh(item)
        iid = item.id
    res = planner.approve_item(iid)
    assert res["committed"] is True
    assert calls["move"][0] == "e9" and calls["move"][3] is True   # user_initiated


# ── operator phases ──────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_morning_phase_removed_no_longer_regenerates_plan(monkeypatch):
    """§A3: the operator-morning phase was deleted because it byte-for-byte
    duplicated the 6:30 planner brief. run_phase('morning') must NOT regenerate
    the plan (it is no longer a valid phase)."""
    import daily_operator as op
    import planner

    called = []

    async def spy_gen(day=None):
        called.append(day)
        return {"source": "test", "task_count": 0, "calendar_count": 2}

    monkeypatch.setattr(op, "_chat_id", lambda: None)
    monkeypatch.setattr(planner, "generate_plan_with_agent", spy_gen)

    assert "morning" not in op.PHASES
    with pytest.raises(ValueError):
        await op.run_phase("morning", day="2026-06-18", send=False)
    assert called == []  # the plan was never regenerated


@pytest.mark.asyncio
async def test_eod_phase_recaps(monkeypatch):
    import daily_operator as op
    import planner
    import operator_brain
    monkeypatch.setattr(op, "_chat_id", lambda: None)
    monkeypatch.setattr(planner, "get_plan", lambda day=None: {"items": [
        {"status": "approved"}, {"status": "rejected"}, {"status": "proposed"}]})

    async def fake_update(day=None):  # keep hermetic — no real agent run
        return {"written": False, "active_threads": 0, "trimmed": 0}
    monkeypatch.setattr(operator_brain, "update_profile", fake_update)

    card = await op.run_phase("eod", day="2026-06-18", send=False)
    assert "EOD recap" in card.headline
    assert "approved 1" in card.lines[0]


# ── op: callback approves all (the user-initiated write) ───────────────────────
def test_op_approveall_callback(monkeypatch):
    import routes.telegram as tg
    from dispatch import dispatcher
    sent = []
    monkeypatch.setattr(dispatcher, "send_telegram_message", lambda c, t, **k: sent.append(t) or 1)

    import planner
    monkeypatch.setattr(planner, "get_plan", lambda day=None: {"items": [
        {"id": 11, "kind": "calendar", "status": "proposed"},
        {"id": 12, "kind": "calendar", "status": "proposed"}]})
    approved = []
    monkeypatch.setattr(planner, "approve_item", lambda i: approved.append(i) or {"committed": True})
    res = tg._handle_operator_callback("op:approveall:2026-06-18", 99)
    assert res["committed"] == 2 and approved == [11, 12]


@pytest.mark.asyncio
async def test_eod_phase_updates_profile(monkeypatch):
    import daily_operator as op
    import planner
    import operator_brain
    monkeypatch.setattr(op, "_chat_id", lambda: None)
    monkeypatch.setattr(planner, "get_plan", lambda day=None: {"items": [
        {"status": "approved"}, {"status": "proposed"}]})

    async def fake_update(day=None):
        return {"written": True, "active_threads": 3, "trimmed": 0}
    monkeypatch.setattr(operator_brain, "update_profile", fake_update)

    card = await op.run_phase("eod", day="2026-06-24", send=False)
    assert "EOD recap" in card.headline
    assert any("Profile updated — 3 active thread" in l for l in card.lines)


@pytest.mark.asyncio
async def test_eod_phase_survives_learner_error(monkeypatch):
    import daily_operator as op
    import planner
    import operator_brain
    monkeypatch.setattr(op, "_chat_id", lambda: None)
    monkeypatch.setattr(planner, "get_plan", lambda day=None: {"items": []})

    async def boom(day=None):
        raise RuntimeError("agent down")
    monkeypatch.setattr(operator_brain, "update_profile", boom)

    card = await op.run_phase("eod", day="2026-06-24", send=False)
    assert "EOD recap" in card.headline  # recap still produced
    assert any("Profile update skipped" in l for l in card.lines)


@pytest.mark.asyncio
async def test_morning_brief_now_lives_in_planner_cron(monkeypatch):
    """§A3: the single morning brief that sends the Telegram digest is the 6:30
    planner cron (scheduler._run_planner), not the operator. Verify that path
    still proposes + sends WITHOUT any autonomous calendar write."""
    import planner
    from dispatch import dispatcher
    from integrations import google_calendar
    from integrations.base import ok

    writes = []
    monkeypatch.setattr(google_calendar, "create_event",
                        lambda event, **k: writes.append(event) or ok("google_calendar", {"id": "x"}))
    sent = []
    monkeypatch.setattr(dispatcher, "send_telegram_message",
                        lambda chat, text, **k: sent.append(text) or 1)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")

    async def fake_gen(day=None):
        return {"source": "agent", "task_count": 1, "calendar_count": 1}
    monkeypatch.setattr(planner, "generate_plan_with_agent", fake_gen)
    monkeypatch.setattr(planner, "plan_digest_text", lambda: "Morning plan ready.")

    from scheduler import SchedulerService
    await SchedulerService()._run_planner()
    assert any("Morning plan ready." in t for t in sent)  # digest sent
    assert writes == []  # propose-only — no autonomous calendar write
