"""Conversation log — the Telegram signal for the nightly learner. Fail-open."""
from datetime import date, datetime, timedelta

import pytest
from sqlmodel import select

import conversation_log as cl
from db import session_scope
from models import ConversationLog


@pytest.fixture(autouse=True)
def _clean():
    with session_scope() as s:
        for r in s.exec(select(ConversationLog)).all():
            s.delete(r)
        s.commit()
    yield


def test_log_and_recent_for_today():
    cl.log_message(42, "user", "ship the planner")
    rows = cl.recent_for_day(date.today().isoformat())
    assert len(rows) == 1
    assert rows[0]["role"] == "user" and rows[0]["text"] == "ship the planner"


def test_recent_excludes_other_days():
    cl.log_message(42, "user", "today only")
    assert cl.recent_for_day("1999-01-01") == []


def test_empty_text_is_ignored():
    cl.log_message(42, "user", "   ")
    assert cl.recent_for_day(date.today().isoformat()) == []


def test_trim_removes_old_keeps_recent():
    cl.log_message(42, "user", "fresh")
    with session_scope() as s:  # backdate one row 40 days
        old = ConversationLog(chat_id=42, role="user", text="stale")
        old.created_at = datetime.utcnow() - timedelta(days=40)
        s.add(old)
        s.commit()
    deleted = cl.trim_older_than(30)
    assert deleted == 1
    texts = [r["text"] for r in cl.recent_for_day(date.today().isoformat())]
    assert "fresh" in texts and "stale" not in texts


def test_logging_failure_is_swallowed(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(cl, "session_scope", boom)
    cl.log_message(42, "user", "should not raise")  # must not raise
