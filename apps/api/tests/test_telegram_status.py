"""Telegram fleet control (Phase 6+): 'status' shows what every agent is doing;
'<agent>: <task>' addresses a specific agent directly."""
from types import SimpleNamespace

import pytest

import models  # noqa: F401 — register tables before conftest's init_db runs
from main import app  # noqa: F401 — registers the agent roster
import routes.telegram as tg
from dispatch import dispatcher
from dispatch.intent import resolve_intent

BO = 6452258223


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", str(BO))
    yield


def _msg(update_id, text):
    return {"update_id": update_id, "message": {"chat": {"id": BO}, "text": text}}


def test_status_command_reports_fleet(monkeypatch):
    sent = []
    monkeypatch.setattr(dispatcher, "send_telegram_message",
                        lambda cid, txt: sent.append(txt) or 1)
    monkeypatch.setattr(tg, "enqueue_job",
                        lambda *a, **k: pytest.fail("status must not enqueue"))
    res = tg.process_update(_msg(800, "status"))
    assert res["status"] == "status"
    assert len(sent) == 1
    # Every registered agent appears in the reply.
    for agent in ("researcher", "trader", "polymarket", "ceo"):
        assert agent in sent[0]


def test_status_aliases(monkeypatch):
    sent = []
    monkeypatch.setattr(dispatcher, "send_telegram_message",
                        lambda cid, txt: sent.append(txt) or 1)
    assert tg.process_update(_msg(801, "agents"))["status"] == "status"
    assert tg.process_update(_msg(802, "  Fleet "))["status"] == "status"


def test_direct_addressing_routes_to_named_agent():
    intent = resolve_intent("trader: how is the cex-lag bot holding up")
    assert intent.agent == "trader" and intent.dispatchable
    intent = resolve_intent("Researcher, dig into the new tariff headlines")
    assert intent.agent == "researcher" and intent.dispatchable


def test_direct_addressing_forbidden_still_refused():
    intent = resolve_intent("trader: buy 10 NVDA")
    assert intent.forbidden is True and intent.dispatchable is False


def test_direct_addressing_unknown_name_falls_through():
    # Not an agent name — normal routing (researcher fallback), not a crash.
    intent = resolve_intent("mom: call me later")
    assert intent.agent == "researcher" and intent.source == "fallback"
