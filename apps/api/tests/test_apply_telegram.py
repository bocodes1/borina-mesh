"""Apply approval surface (Phase 1): the apply: command stages + cards; the
apply:send tap is the user-initiated send; apply:skip sends nothing. Mirrors
test_telegram_commands' capture fixture + the operator-callback tests."""
import pytest

import routes.telegram as tg
from dispatch import dispatcher
from dispatch import apply as ap


@pytest.fixture(autouse=True)
def _capture(monkeypatch):
    from db import engine
    import fleet_roster as fr
    fr.seed_roster(engine)
    sent = []

    def _fake_send(chat_id, text, reply_markup=None):
        sent.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})
        return 1

    monkeypatch.setattr(dispatcher, "send_telegram_message", _fake_send)
    return sent


def test_apply_card_has_send_and_skip(monkeypatch):
    card = tg.apply_card({"id": 7, "track": "swe", "company": "Acme AI",
                          "contact_email": "ada@acme.ai", "subject": "S", "body": "B"})
    datas = [a.data for a in card.actions]
    assert "apply:send:7" in datas and "apply:skip:7" in datas


def test_apply_send_callback_invokes_approve_send(monkeypatch, _capture):
    calls = []
    monkeypatch.setattr(ap, "approve_send", lambda i: calls.append(i) or {"status": "sent", "company": "Acme AI"})
    res = tg._handle_apply_callback("apply:send:7", 99)
    assert res["status"] == "apply_send"
    assert calls == [7]


def test_apply_skip_callback_invokes_skip(monkeypatch, _capture):
    calls = []
    monkeypatch.setattr(ap, "skip_item", lambda i: calls.append(i) or {"status": "skipped"})
    res = tg._handle_apply_callback("apply:skip:7", 99)
    assert res["status"] == "apply_skip"
    assert calls == [7]


def test_handle_callback_routes_apply_prefix(monkeypatch, _capture):
    monkeypatch.setattr(ap, "skip_item", lambda i: {"status": "skipped"})
    res = tg._handle_callback("apply:skip:3", 99)
    assert res["status"] == "apply_skip"


def test_apply_command_stages_and_cards(monkeypatch, _capture):
    BO = 6452258223
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", str(BO))

    async def fake_run(criteria="", chat_id=None):
        return {"staged": 1, "dropped": 1, "item_ids": [11],
                "reasons": ["X: no confident email"]}

    monkeypatch.setattr(ap, "run_apply", fake_run)
    monkeypatch.setattr(ap, "get_proposed", lambda: [
        {"id": 11, "track": "swe", "company": "Acme AI",
         "contact_email": "ada@acme.ai", "subject": "S", "body": "B"}])

    update = {"update_id": 1, "message": {"chat": {"id": BO}, "text": "apply: AI fintech remote"}}
    res = tg.process_update(update)
    assert res["status"] == "apply_started"
    # at least one card carried the Send button
    datas = [b["callback_data"] for m in _capture if m["reply_markup"]
             for row in m["reply_markup"]["inline_keyboard"] for b in row]
    assert "apply:send:11" in datas
    # the drop count is surfaced (no silent caps)
    assert any("1 dropped" in m["text"] or "dropped" in m["text"].lower() for m in _capture)
