"""Conversational lane — quick reply + calendar-event extraction → approval card."""
import json

import pytest

from dispatch import converse as cv


@pytest.fixture(autouse=True)
def _db():
    from db import engine
    import models  # noqa: F401
    from sqlmodel import SQLModel
    SQLModel.metadata.create_all(engine)
    yield


def test_converse_parses_reply_and_event(monkeypatch):
    monkeypatch.setattr(cv, "_claude", lambda p, timeout=45: json.dumps({
        "reply": "Got it — Monday around noon.",
        "event": {"summary": "Photo shoot", "start": "2026-06-22T12:00:00", "end": "2026-06-22T13:00:00"},
    }))
    out = cv.converse("photo shoot Monday 12pm")
    assert out["reply"].startswith("Got it")
    assert out["event"]["summary"] == "Photo shoot"


def test_converse_plain_chat_has_no_event(monkeypatch):
    monkeypatch.setattr(cv, "_claude", lambda p, timeout=45: json.dumps({
        "reply": "Looks clear, ~21C in Toronto.", "event": None}))
    out = cv.converse("what's the vibe for monday")
    assert out["event"] is None
    assert "21C" in out["reply"]


def test_converse_survives_bad_json(monkeypatch):
    monkeypatch.setattr(cv, "_claude", lambda p, timeout=45: "just some plain text, no json")
    out = cv.converse("hi")
    assert out["event"] is None
    assert "plain text" in out["reply"]


def test_converse_survives_empty(monkeypatch):
    monkeypatch.setattr(cv, "_claude", lambda p, timeout=45: "")
    out = cv.converse("hi")
    assert out["event"] is None
    assert out["reply"]                       # a friendly fallback, not empty


def test_event_card_uses_approve_reject_verbs():
    ev = {"summary": "Dentist", "start": "2026-06-23T15:00:00", "end": "2026-06-23T16:00:00"}
    iid = cv.stage_event_item(ev)
    card = cv.event_card(ev, iid)
    datas = [a.data for a in card.actions]
    assert datas == [f"approve:{iid}", f"op:edit:{iid}", f"reject:{iid}"]
    assert "Dentist" in card.lines[0]


def test_stage_event_item_creates_proposed_calendar_planitem():
    from db import session_scope
    from models import PlanItem
    iid = cv.stage_event_item({"summary": "Call", "start": "2026-06-23T09:00:00"})
    with session_scope() as s:
        item = s.get(PlanItem, iid)
        assert item.kind == "calendar" and item.status == "proposed"
        payload = json.loads(item.payload_json)
        assert payload["op"] == "create" and payload["summary"] == "Call"
        assert payload["end"]                 # auto-filled +1h


def test_handle_converse_sends_reply_and_card(monkeypatch):
    sent, cards = [], []
    monkeypatch.setattr(cv, "_claude", lambda p, timeout=45: json.dumps({
        "reply": "Noted!", "event": {"summary": "Shoot", "start": "2026-06-22T12:00:00"}}))
    from dispatch import dispatcher
    monkeypatch.setattr(dispatcher, "send_telegram_message", lambda c, t, **k: sent.append(t) or 1)
    monkeypatch.setattr("dispatch.cards.send_card", lambda c, card: cards.append(card) or 1)
    res = cv.handle_converse("photo shoot monday noon", 99)
    assert res["status"] == "converse_event"
    assert any("Noted" in s for s in sent)    # conversational reply sent
    assert cards and cards[0].headline == "Add to calendar?"


def test_routing_casual_message_goes_to_converse(monkeypatch):
    # A casual message routes to the conversational lane (fallback), not a heavy
    # dispatch and not a refusal.
    import routes.telegram as tg
    from dispatch.intent import resolve_intent
    intent = resolve_intent("i have a photo shoot on monday around 12pm")
    assert intent.source == "fallback" and intent.forbidden is False
