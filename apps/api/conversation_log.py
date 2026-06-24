"""Telegram conversation log — the Telegram signal for the nightly learner.

Every inbound user message (post allow-list) and Borina reply is appended here
fail-open: logging never raises into the dispatch path. The learner reads one
day's window; a nightly trim keeps the table bounded.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlmodel import select

from db import session_scope
from models import ConversationLog


def log_message(chat_id: int, role: str, text: str) -> None:
    """Append one message. Swallows every error — must never break dispatch."""
    text = (text or "").strip()
    if not text:
        return
    try:
        with session_scope() as s:
            s.add(ConversationLog(chat_id=chat_id, role=role, text=text[:4000]))
            s.commit()
    except Exception:  # noqa: BLE001 — logging is best-effort
        pass


def recent_for_day(day: str) -> list[dict]:
    """Messages whose created_at falls on `day` (YYYY-MM-DD), oldest-first.
    Returns [] on any error."""
    try:
        with session_scope() as s:
            rows = s.exec(
                select(ConversationLog).order_by(ConversationLog.created_at)
            ).all()
        return [
            {"role": r.role, "text": r.text, "at": r.created_at.isoformat()}
            for r in rows
            if r.created_at.date().isoformat() == day
        ]
    except Exception:  # noqa: BLE001
        return []


def trim_older_than(days: int = 30) -> int:
    """Delete rows older than `days`. Returns count deleted (0 on error)."""
    try:
        cutoff = datetime.utcnow() - timedelta(days=days)
        deleted = 0
        with session_scope() as s:
            for r in s.exec(
                select(ConversationLog).where(ConversationLog.created_at < cutoff)
            ).all():
                s.delete(r)
                deleted += 1
            s.commit()
        return deleted
    except Exception:  # noqa: BLE001
        return 0
