"""Weekly digest + reply/follow-up sweep on the Monday cron (Phase 3). The cron
detects replies (read-only), stages follow-ups (no send), stages the email +
posting batch, and posts a digest card. NEVER sends. Mirrors test_apply_scheduler
+ register_fleet_health."""
from datetime import datetime, timedelta

import pytest
from sqlmodel import select

from db import session_scope
from models import OutreachItem, OutreachReply
from scheduler import SchedulerService
from dispatch.cards import Card


@pytest.fixture(autouse=True)
def _clean():
    with session_scope() as s:
        for r in s.exec(select(OutreachReply)).all():
            s.delete(r)
        for it in s.exec(select(OutreachItem)).all():
            s.delete(it)
        s.commit()
    yield


def _seed(company, status, *, days_ago=1):
    with session_scope() as s:
        it = OutreachItem(track="swe", company=company, contact_email=f"x@{company}.ai",
                          subject="S", body="B", dedup_key=f"x@{company}.ai|{company}",
                          status=status, company_domain=f"{company}.ai")
        it.sent_at = datetime.utcnow() - timedelta(days=days_ago)
        s.add(it)
        s.commit()


def test_digest_card_summarizes_counts():
    _seed("acme", "sent")
    _seed("finco", "replied")
    svc = SchedulerService()
    card = svc._digest_card()
    assert isinstance(card, Card)
    blob = card.headline + " ".join(card.lines)
    assert "1 sent" in blob or "sent" in blob.lower()
    assert "replied" in blob.lower() or "repl" in blob.lower()


@pytest.mark.asyncio
async def test_run_apply_weekly_sweeps_and_never_sends(monkeypatch):
    from dispatch import apply as ap
    from integrations import outlook
    from integrations.base import ok

    sent = []
    monkeypatch.setattr(outlook, "send_mail",
                        lambda *a, **k: sent.append(1) or ok("outlook", {"id": "x", "via": "graph"}))

    swept = {"replies": 0, "followups": 0, "batch": 0}

    def fake_match(since_iso=None):
        swept["replies"] += 1
        return {"matched": 0, "replied_item_ids": [], "flags": {}, "reasons": []}

    async def fake_followups(now=None):
        swept["followups"] += 1
        return {"staged": 0, "dropped": 0, "item_ids": [], "reasons": []}

    async def fake_run(criteria="", chat_id=None):
        swept["batch"] += 1
        return {"staged": 0, "dropped": 0, "item_ids": [], "reasons": []}

    async def fake_postings(criteria="", chat_id=None):
        return {"staged": 0, "dropped": 0, "item_ids": [], "reasons": []}

    monkeypatch.setattr(ap, "match_replies", fake_match)
    monkeypatch.setattr(ap, "stage_followups", fake_followups)
    monkeypatch.setattr(ap, "run_apply", fake_run)
    monkeypatch.setattr(ap, "run_postings", fake_postings)
    monkeypatch.setattr(ap, "get_proposed_postings", lambda: [])
    monkeypatch.setattr("routes.telegram.send_apply_cards", lambda chat_id: 0)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    svc = SchedulerService()
    await svc._run_apply_weekly()
    assert swept == {"replies": 1, "followups": 1, "batch": 1}
    assert sent == []                               # the cron never sends
