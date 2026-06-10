"""Telegram getUpdates polling mode (Phase 4 §3) — webhook-free inbound.

The poller must reuse the SAME fail-closed pipeline as the webhook (allow-list →
intent → idempotent enqueue). It is off unless TELEGRAM_DISPATCH_MODE=polling
AND a bot token is set, so tests/dev never accidentally long-poll Telegram.
"""
import asyncio
from types import SimpleNamespace

import pytest

import routes.telegram as tg
from dispatch import dispatcher, poller as poller_mod
from dispatch.poller import TelegramPoller, enabled

BO = 6452258223


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr(dispatcher, "send_telegram_message", lambda *a, **k: None)
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", str(BO))


def _spy_enqueue(monkeypatch):
    calls = []

    def fake(text, agent, update_id, chat_id):
        calls.append({"agent": agent, "chat_id": chat_id, "update_id": update_id, "text": text})
        return SimpleNamespace(id=len(calls))

    monkeypatch.setattr(tg, "enqueue_job", fake)
    return calls


def _msg(update_id, chat_id, text):
    return {"update_id": update_id, "message": {"chat": {"id": chat_id}, "text": text}}


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("TELEGRAM_DISPATCH_MODE", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t0k3n")
    assert enabled() is False


def test_enabled_requires_mode_and_token(monkeypatch):
    monkeypatch.setenv("TELEGRAM_DISPATCH_MODE", "polling")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t0k3n")
    assert enabled() is True
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    assert enabled() is False


def test_start_is_noop_when_disabled(monkeypatch):
    monkeypatch.delenv("TELEGRAM_DISPATCH_MODE", raising=False)
    p = TelegramPoller()

    async def go():
        p.start()
        assert p._task is None

    asyncio.run(go())


def test_poll_once_routes_allowed_update_to_enqueue(monkeypatch):
    calls = _spy_enqueue(monkeypatch)
    updates = [_msg(101, BO, "research NVDA earnings")]
    p = TelegramPoller(fetch=lambda offset: updates)
    n = asyncio.run(p.poll_once())
    assert n == 1
    assert len(calls) == 1 and calls[0]["chat_id"] == BO and calls[0]["update_id"] == 101
    # offset advanced past the consumed update (acks it to Telegram).
    assert p.offset == 102


def test_poll_once_drops_non_allowed_chat(monkeypatch):
    calls = _spy_enqueue(monkeypatch)
    p = TelegramPoller(fetch=lambda offset: [_msg(200, 999, "research X")])
    asyncio.run(p.poll_once())
    assert calls == []  # fail-closed allow-list, same as the webhook
    assert p.offset == 201  # still acked — never re-deliver a dropped update


def test_poll_once_survives_processing_error(monkeypatch):
    def boom(update):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(tg, "process_update", boom)
    p = TelegramPoller(fetch=lambda offset: [_msg(300, BO, "hello")])
    asyncio.run(p.poll_once())  # must not raise
    assert p.offset == 301


def test_process_update_shared_with_webhook(monkeypatch):
    """The webhook route and the poller go through the same function."""
    calls = _spy_enqueue(monkeypatch)
    res = tg.process_update(_msg(400, BO, "research the bond market"))
    assert res["status"] == "dispatched"
    assert calls[0]["update_id"] == 400
