"""Follow-up staging (Phase 3). No reply after 7 days → ONE staged follow-up per
contact, respecting the daily cap + blocklist. Staging NEVER sends — the
follow-up rides Phase 1's approve_send gate. draft_email is stubbed (no agent
CLI). Mirrors test_apply_pipeline's clean + no-send invariant."""
from datetime import datetime, timedelta

import pytest
from sqlmodel import select

from db import session_scope
from models import OutreachItem
from dispatch import apply as ap
from integrations import outlook
from integrations.base import ok


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    with session_scope() as s:
        for it in s.exec(select(OutreachItem)).all():
            s.delete(it)
        s.commit()
    # No real agent CLI for the follow-up draft.
    async def fake_draft(candidate, contact):
        return {"subject": f"Following up — {candidate['company']}",
                "body": "Just bumping this — still keen on internships."}
    monkeypatch.setattr(ap, "draft_email", fake_draft)
    # Blocklist empty unless a test overrides it.
    monkeypatch.setattr(ap, "_load_blocklist", lambda: set())
    yield


def _seed(email, *, status="sent", days_ago=10, dedup=None):
    with session_scope() as s:
        it = OutreachItem(track="swe", company="Acme AI", contact_email=email,
                          subject="Internship", body="hi", company_domain="acme.ai",
                          dedup_key=dedup or ap._dedup_key(email, "acme.ai"), status=status)
        it.created_at = datetime.utcnow() - timedelta(days=days_ago)
        it.sent_at = datetime.utcnow() - timedelta(days=days_ago)
        s.add(it)
        s.commit()
        s.refresh(it)
        return it.id


def _spy_no_send(monkeypatch):
    calls = []
    monkeypatch.setattr(outlook, "send_mail",
                        lambda *a, **k: calls.append(1) or ok("outlook", {"id": "x", "via": "graph"}))
    return calls


@pytest.mark.asyncio
async def test_stages_followup_after_window_and_never_sends(monkeypatch):
    _seed("ada@acme.ai", days_ago=10)
    calls = _spy_no_send(monkeypatch)
    summary = await ap.stage_followups()
    assert summary["staged"] == 1
    assert calls == []                              # staging never sends
    with session_scope() as s:
        rows = s.exec(select(OutreachItem).where(OutreachItem.status == "proposed")).all()
        assert len(rows) == 1
        assert rows[0].dedup_key.startswith(ap.FOLLOWUP_PREFIX)


@pytest.mark.asyncio
async def test_recent_send_is_not_followed_up(monkeypatch):
    _seed("ada@acme.ai", days_ago=2)                # inside the 7-day window
    summary = await ap.stage_followups()
    assert summary["staged"] == 0
    assert any("too recent" in r.lower() for r in summary["reasons"])


@pytest.mark.asyncio
async def test_replied_item_is_not_followed_up(monkeypatch):
    _seed("ada@acme.ai", status="replied", days_ago=10)
    summary = await ap.stage_followups()
    assert summary["staged"] == 0


@pytest.mark.asyncio
async def test_one_followup_per_contact(monkeypatch):
    _seed("ada@acme.ai", days_ago=10)
    await ap.stage_followups()
    summary2 = await ap.stage_followups()           # follow-up already exists
    assert summary2["staged"] == 0
    assert any("already followed up" in r.lower() for r in summary2["reasons"])


@pytest.mark.asyncio
async def test_blocklist_is_honored(monkeypatch):
    _seed("ada@acme.ai", days_ago=10)
    monkeypatch.setattr(ap, "_load_blocklist", lambda: {"ada@acme.ai"})
    summary = await ap.stage_followups()
    assert summary["staged"] == 0
    assert any("blocklist" in r.lower() for r in summary["reasons"])


@pytest.mark.asyncio
async def test_daily_cap_limits_followups(monkeypatch):
    for i in range(ap.DAILY_SEND_CAP + 3):
        _seed(f"c{i}@acme.ai", days_ago=10, dedup=f"c{i}@acme.ai|acme.ai")
    summary = await ap.stage_followups()
    assert summary["staged"] == ap.DAILY_SEND_CAP
    assert summary["dropped"] >= 3
    assert any("daily cap" in r.lower() for r in summary["reasons"])
