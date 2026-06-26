"""Posting pipeline (Phase 2). CORE INVARIANT: staging NEVER submits. Only
submit_posting reaches an outbound path, and email reuses send_mail with
user_initiated=True; form fills then STOPS before submit; external hands off.
Externals (discover/prepare/send/fill) stubbed — no real network/browser/agent."""
import json

import pytest
from sqlmodel import select

from db import session_scope
from models import PostingApplication
from dispatch import apply as ap
from dispatch import postings as pg
from integrations import outlook
from integrations.base import ok, not_connected


@pytest.fixture(autouse=True)
def _clean():
    with session_scope() as s:
        for it in s.exec(select(PostingApplication)).all():
            s.delete(it)
        s.commit()
    yield


def _stub_discovery(monkeypatch, postings=None):
    postings = postings if postings is not None else [
        {"track": "swe", "source": "wellfound", "company": "Acme AI",
         "role_title": "AI SWE Intern", "location": "Toronto",
         "posting_url": "https://boards.greenhouse.io/acme/jobs/9",
         "submit_method": "form", "ats": "greenhouse", "apply_email": None},
        {"track": "finance", "source": "yc", "company": "FinML",
         "role_title": "Quant Intern", "location": "Remote",
         "posting_url": "https://finml.com/apply", "submit_method": "email",
         "ats": None, "apply_email": "jobs@finml.com"},
    ]
    monkeypatch.setattr(pg, "discover_postings", lambda criteria="": list(postings))

    async def fake_prepare(posting):
        return {"cover_letter": f"Dear {posting['company']} team, ...",
                "answers": {"why": f"I admire {posting['company']}'s AI work."}}

    monkeypatch.setattr(ap, "prepare_posting", fake_prepare)


def _spy_send(monkeypatch):
    calls = []

    def fake_send(recipients, subject, body, *, attachments=None, user_initiated=False, send_via=None):
        calls.append({"recipients": recipients, "user_initiated": user_initiated})
        return ok("outlook", {"id": "sent-1", "via": "graph"})

    monkeypatch.setattr(outlook, "send_mail", fake_send)
    return calls


def _spy_fill(monkeypatch):
    calls = []

    def fake_fill(self, posting_url, fields, *, resume_path=None):
        calls.append({"url": posting_url, "fields": fields})
        return {"filled": True, "submitted": False, "review_url": posting_url}

    monkeypatch.setattr(outlook.BrowserFiller, "fill", fake_fill)
    return calls


@pytest.mark.asyncio
async def test_run_postings_stages_and_never_submits(monkeypatch):
    _stub_discovery(monkeypatch)
    sends = _spy_send(monkeypatch)
    fills = _spy_fill(monkeypatch)
    summary = await ap.run_postings("AI internships")
    assert summary["staged"] == 2
    # CORE INVARIANT: staging neither sent nor filled anything.
    assert sends == [] and fills == []
    with session_scope() as s:
        rows = s.exec(select(PostingApplication)).all()
        assert len(rows) == 2
        assert all(r.status == "proposed" for r in rows)
        # prepare wrote cover letters + answers (text only).
        assert all(r.cover_letter for r in rows)
        assert all(json.loads(r.answers_json) for r in rows)


@pytest.mark.asyncio
async def test_postings_dedup(monkeypatch):
    _stub_discovery(monkeypatch)
    _spy_send(monkeypatch)
    _spy_fill(monkeypatch)
    await ap.run_postings()
    summary2 = await ap.run_postings()
    assert summary2["staged"] == 0
    assert summary2["dropped"] == 2
    assert any("dedup" in r.lower() for r in summary2["reasons"])


@pytest.mark.asyncio
async def test_submit_email_posting_is_user_initiated(monkeypatch):
    _stub_discovery(monkeypatch)
    await ap.run_postings()
    sends = _spy_send(monkeypatch)
    fills = _spy_fill(monkeypatch)
    email_item = next(p for p in ap.get_proposed_postings() if p["submit_method"] == "email")
    res = ap.submit_posting(email_item["id"])
    assert res["status"] == "submitted" and res["method"] == "email"
    assert len(sends) == 1 and sends[0]["user_initiated"] is True
    assert sends[0]["recipients"] == ["jobs@finml.com"]
    assert fills == []  # email path never touches the browser filler
    # idempotent
    res2 = ap.submit_posting(email_item["id"])
    assert res2.get("already_decided") is True
    assert len(sends) == 1


@pytest.mark.asyncio
async def test_submit_form_posting_fills_but_does_not_submit(monkeypatch):
    _stub_discovery(monkeypatch)
    await ap.run_postings()
    sends = _spy_send(monkeypatch)
    fills = _spy_fill(monkeypatch)
    form_item = next(p for p in ap.get_proposed_postings() if p["submit_method"] == "form")
    res = ap.submit_posting(form_item["id"])
    # form fill STOPS before submit → status 'prepared', human submits.
    assert res["status"] == "prepared" and res["method"] == "form"
    assert res["review_url"].endswith("/9")
    assert len(fills) == 1
    assert sends == []  # form path never sends email
    with session_scope() as s:
        row = s.get(PostingApplication, form_item["id"])
        assert row.status == "prepared"  # NOT submitted — Bo clicks submit himself


@pytest.mark.asyncio
async def test_submit_external_posting_hands_off(monkeypatch):
    ext = [{"track": "swe", "source": "career_page", "company": "BigCo",
            "role_title": "AI Intern", "location": "Toronto",
            "posting_url": "https://bigco.wd1.myworkdayjobs.com/x/job/1",
            "submit_method": "external", "ats": "workday", "apply_email": None}]
    _stub_discovery(monkeypatch, postings=ext)
    await ap.run_postings()
    sends = _spy_send(monkeypatch)
    fills = _spy_fill(monkeypatch)
    item = ap.get_proposed_postings()[0]
    res = ap.submit_posting(item["id"])
    assert res["status"] == "prepared" and res["method"] == "external"
    assert res["handoff"]["posting_url"].endswith("/job/1")
    assert res["handoff"]["cover_letter"]
    # external never auto-fills or sends.
    assert sends == [] and fills == []


@pytest.mark.asyncio
async def test_submit_form_fill_failure_stays_retryable(monkeypatch):
    _stub_discovery(monkeypatch)
    await ap.run_postings()

    def boom_fill(self, posting_url, fields, *, resume_path=None):
        raise RuntimeError("browser not wired")

    monkeypatch.setattr(outlook.BrowserFiller, "fill", boom_fill)
    form_item = next(p for p in ap.get_proposed_postings() if p["submit_method"] == "form")
    res = ap.submit_posting(form_item["id"])
    assert res["status"] == "failed" and res["error"]
    with session_scope() as s:
        row = s.get(PostingApplication, form_item["id"])
        assert row.status == "failed" and row.error  # not lost


@pytest.mark.asyncio
async def test_skip_posting_does_nothing(monkeypatch):
    _stub_discovery(monkeypatch)
    await ap.run_postings()
    sends = _spy_send(monkeypatch)
    fills = _spy_fill(monkeypatch)
    item = ap.get_proposed_postings()[0]
    res = ap.skip_posting(item["id"])
    assert res["status"] == "skipped"
    assert sends == [] and fills == []
