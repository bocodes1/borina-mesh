"""Telegram threads: replying to a bot report message continues that topic
with the SAME agent. The bot's outbound report message_id is recorded per job;
process_update consults it before intent resolution. Forbidden gate still
runs on follow-up text."""
import asyncio
from types import SimpleNamespace

import pytest
from sqlmodel import Session, select

import models  # noqa: F401 — register tables before conftest's init_db runs
import routes.telegram as tg
from db import engine, session_scope
from dispatch import dispatcher
from dispatch.intent import Intent
from models import TelegramThread

BO = 6452258223


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", str(BO))
    monkeypatch.setattr(dispatcher, "send_telegram_message", lambda *a, **k: None)
    with session_scope() as s:
        for t in s.exec(select(TelegramThread)).all():
            s.delete(t)
        s.commit()
    yield


def test_record_and_find_thread():
    dispatcher._record_thread(chat_id=BO, message_id=555, agent_id="trader",
                              job_id=12, prompt="bot health")
    t = dispatcher.find_thread(chat_id=BO, message_id=555)
    assert t is not None and t.agent_id == "trader" and t.job_id == 12
    assert dispatcher.find_thread(chat_id=BO, message_id=999) is None


def test_produce_and_reply_records_thread(monkeypatch, tmp_path):
    async def fake_run_agent(agent_id, prompt):
        return "# r\n\nbody"

    monkeypatch.setattr(dispatcher, "run_agent", fake_run_agent)
    monkeypatch.setattr(dispatcher, "render_markdown_pdf", lambda md, p: p)
    monkeypatch.setattr(dispatcher, "send_telegram_message", lambda *a, **k: 777)
    monkeypatch.setattr(dispatcher, "send_telegram_document", lambda *a, **k: None)
    intent = Intent(raw_text="bot health check", agent="trader",
                    task_type="bot_health", confidence=0.8, source="alias")
    asyncio.run(dispatcher.dispatch_intent(intent, chat_id=BO))
    with Session(engine) as s:
        threads = s.exec(select(TelegramThread).where(TelegramThread.message_id == 777)).all()
    assert len(threads) == 1 and threads[0].agent_id == "trader"
