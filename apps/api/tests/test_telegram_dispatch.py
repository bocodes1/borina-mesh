"""Telegram webhook security boundary (spec §8b.2 / §8b.7 / §10b).

The security-critical suite: allow-list, fail-closed, secret-token, forbidden
refusal, and that a valid update enqueues the right agent fast.
"""
import pytest
from fastapi.testclient import TestClient

from main import app
import routes.telegram as tg
from dispatch import dispatcher

client = TestClient(app)

SECRET = "s3cr3t"
BO = 6452258223
HEADERS = {"X-Telegram-Bot-Api-Secret-Token": SECRET}


@pytest.fixture(autouse=True)
def _no_real_sends(monkeypatch):
    # Never hit the Telegram API in tests.
    monkeypatch.setattr(dispatcher, "send_telegram_message", lambda *a, **k: None)
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", SECRET)


def _spy_enqueue(monkeypatch):
    calls = []
    monkeypatch.setattr(tg, "enqueue_dispatch", lambda bg, intent, chat_id, ts: calls.append((intent, chat_id)))
    return calls


def _update(chat_id, text):
    return {"message": {"chat": {"id": chat_id}, "text": text}}


def test_missing_secret_rejected(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", str(BO))
    calls = _spy_enqueue(monkeypatch)
    r = client.post("/api/telegram/webhook", json=_update(BO, "research AI"))  # no header
    assert r.status_code == 403
    assert calls == []


def test_wrong_secret_rejected(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", str(BO))
    calls = _spy_enqueue(monkeypatch)
    r = client.post("/api/telegram/webhook", json=_update(BO, "research AI"),
                    headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"})
    assert r.status_code == 403
    assert calls == []


def test_non_allowlisted_chat_silently_ignored(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", str(BO))
    calls = _spy_enqueue(monkeypatch)
    r = client.post("/api/telegram/webhook", json=_update(999999, "research AI"), headers=HEADERS)
    assert r.status_code == 200 and r.json()["status"] == "ignored"
    assert calls == []  # no dispatch


def test_empty_allowlist_fails_closed(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "")  # misconfigured
    calls = _spy_enqueue(monkeypatch)
    r = client.post("/api/telegram/webhook", json=_update(BO, "research AI"), headers=HEADERS)
    assert r.status_code == 200 and r.json()["status"] == "ignored"
    assert calls == []  # nobody is allowed


def test_valid_update_enqueues_right_agent(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", str(BO))
    calls = _spy_enqueue(monkeypatch)
    r = client.post(
        "/api/telegram/webhook",
        json=_update(BO, "verify the daily report of my stocks and any news on my investments"),
        headers=HEADERS,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "dispatched" and body["agent"] == "researcher"
    assert len(calls) == 1
    intent, chat_id = calls[0]
    assert intent.agent == "researcher" and chat_id == BO


def test_forbidden_action_refused_no_dispatch(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", str(BO))
    calls = _spy_enqueue(monkeypatch)
    r = client.post("/api/telegram/webhook", json=_update(BO, "sell all my NVDA shares"), headers=HEADERS)
    assert r.status_code == 200 and r.json()["status"] == "refused"
    assert calls == []  # nothing dispatched
