"""Cold-email pipeline (Phase 1). CORE INVARIANT: staging NEVER sends. Only
approve_send calls outlook.send_mail, and only with user_initiated=True. skip
sends nothing. Externals (discover/enrich/draft/send) are stubbed — no real
network, browser, or agent CLI. Mirrors test_planner's spy + lifecycle tests."""
import pytest
from sqlmodel import select

from db import session_scope
from models import OutreachItem
from dispatch import apply as ap
from integrations import contacts, outlook
from integrations.base import ok, not_connected


@pytest.fixture(autouse=True)
def _clean():
    with session_scope() as s:
        for it in s.exec(select(OutreachItem)).all():
            s.delete(it)
        s.commit()
    yield


def _stub_pipeline(monkeypatch, *, contact=None):
    # Deterministic discover: two candidates, one per track.
    monkeypatch.setattr(ap, "discover", lambda criteria="": [
        {"company": "Acme AI", "domain": "acme.ai", "why_fit": "LLM infra", "track": "swe"},
        {"company": "FinML", "domain": "finml.com", "why_fit": "quant AI", "track": "finance"},
    ])
    # Enrich: confident contact for both unless overridden.
    good = contact or {"name": "Ada Lee", "email": "ada@acme.ai", "confidence": 90, "domain": "acme.ai"}

    def fake_find(company, domain):
        return ok("contacts", {**good, "email": f"hire@{domain}", "domain": domain})

    monkeypatch.setattr(contacts, "find_contact", fake_find)

    # Draft: no real agent CLI.
    async def fake_draft(candidate, contact):
        return {"subject": f"Internship — {candidate['company']}",
                "body": f"Hi, re your {candidate['why_fit']} work."}

    monkeypatch.setattr(ap, "draft_email", fake_draft)


def _spy_send(monkeypatch):
    calls = []

    def fake_send(recipients, subject, body, *, attachments=None, user_initiated=False, send_via=None):
        calls.append({"recipients": recipients, "user_initiated": user_initiated})
        return ok("outlook", {"id": "sent-1", "via": "graph"})

    monkeypatch.setattr(outlook, "send_mail", fake_send)
    return calls


@pytest.mark.asyncio
async def test_run_apply_stages_and_never_sends(monkeypatch):
    _stub_pipeline(monkeypatch)
    calls = _spy_send(monkeypatch)
    summary = await ap.run_apply("AI internships")
    assert summary["staged"] == 2
    # CORE INVARIANT: staging sent nothing.
    assert calls == []
    with session_scope() as s:
        rows = s.exec(select(OutreachItem)).all()
        assert len(rows) == 2
        assert all(r.status == "proposed" for r in rows)


@pytest.mark.asyncio
async def test_no_send_regression(monkeypatch):
    """Explicit guard: building/regenerating a batch must never call send_mail."""
    _stub_pipeline(monkeypatch)
    calls = _spy_send(monkeypatch)
    await ap.run_apply()
    await ap.run_apply()
    assert calls == [], "pipeline must never auto-send"


@pytest.mark.asyncio
async def test_enrichment_drop_is_reported(monkeypatch):
    _stub_pipeline(monkeypatch)

    def fake_find(company, domain):
        return not_connected("contacts", "no confident email")

    monkeypatch.setattr(contacts, "find_contact", fake_find)
    summary = await ap.run_apply()
    assert summary["staged"] == 0
    assert summary["dropped"] == 2
    assert any("no confident email" in r for r in summary["reasons"])


@pytest.mark.asyncio
async def test_dedup_skips_already_staged(monkeypatch):
    _stub_pipeline(monkeypatch)
    await ap.run_apply()
    summary2 = await ap.run_apply()  # same candidates → deduped
    assert summary2["staged"] == 0
    assert summary2["dropped"] == 2
    assert any("dedup" in r.lower() for r in summary2["reasons"])


@pytest.mark.asyncio
async def test_approve_send_is_the_only_user_initiated_path(monkeypatch):
    _stub_pipeline(monkeypatch)
    await ap.run_apply()
    calls = _spy_send(monkeypatch)
    item = ap.get_proposed()[0]
    res = ap.approve_send(item["id"])
    assert res["status"] == "sent"
    assert len(calls) == 1 and calls[0]["user_initiated"] is True
    # idempotent: approving again sends nothing more.
    res2 = ap.approve_send(item["id"])
    assert res2.get("already_decided") is True
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_failed_send_stays_retryable(monkeypatch):
    _stub_pipeline(monkeypatch)
    await ap.run_apply()

    def fail_send(recipients, subject, body, *, attachments=None, user_initiated=False, send_via=None):
        return not_connected("outlook", "Outlook not authorized")

    monkeypatch.setattr(outlook, "send_mail", fail_send)
    item = ap.get_proposed()[0]
    res = ap.approve_send(item["id"])
    assert res["status"] == "failed"
    # still queryable as failed with an error, not lost.
    with session_scope() as s:
        row = s.get(OutreachItem, item["id"])
        assert row.status == "failed" and row.error


@pytest.mark.asyncio
async def test_skip_sends_nothing(monkeypatch):
    _stub_pipeline(monkeypatch)
    await ap.run_apply()
    calls = _spy_send(monkeypatch)
    item = ap.get_proposed()[0]
    res = ap.skip_item(item["id"])
    assert res["status"] == "skipped"
    assert calls == []
