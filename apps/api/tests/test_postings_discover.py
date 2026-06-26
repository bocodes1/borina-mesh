"""Board discovery (Phase 2). Fetch is the http_get_json seam — stubbed, no real
network. classify_submit routes greenhouse/lever→form, email→email,
workday/captcha→external. Discovery never sends or submits. Mirrors
test_apply_pipeline's stubbing style."""
import pytest

from dispatch import postings as pg


def test_classify_email_posting():
    method, ats = pg.classify_submit(
        {"apply_email": "jobs@acme.ai", "posting_url": "https://acme.ai/careers/1"})
    assert method == "email" and ats is None


def test_classify_greenhouse_is_form():
    method, ats = pg.classify_submit(
        {"posting_url": "https://boards.greenhouse.io/acme/jobs/123"})
    assert method == "form" and ats == "greenhouse"


def test_classify_lever_is_form():
    method, ats = pg.classify_submit(
        {"posting_url": "https://jobs.lever.co/acme/abc"})
    assert method == "form" and ats == "lever"


def test_classify_workday_is_external():
    method, ats = pg.classify_submit(
        {"posting_url": "https://acme.wd1.myworkdayjobs.com/x/job/1"})
    assert method == "external" and ats == "workday"


def test_classify_captcha_is_external():
    method, ats = pg.classify_submit(
        {"posting_url": "https://boards.greenhouse.io/acme/jobs/1", "captcha": True})
    assert method == "external"


def test_discover_postings_normalizes_and_classifies(monkeypatch):
    def fake_get(url, *, params=None, headers=None, timeout=None):
        if "wellfound" in url:
            return {"jobs": [
                {"company": "Acme AI", "title": "AI SWE Intern", "location": "Toronto",
                 "url": "https://boards.greenhouse.io/acme/jobs/9", "track": "swe"},
            ]}
        if "ycombinator" in url:
            return {"jobs": [
                {"company": "FinML", "title": "Quant Intern", "location": "Remote",
                 "url": "https://finml.com/apply", "apply_email": "jobs@finml.com",
                 "track": "finance"},
            ]}
        return {"jobs": []}  # career_page seed empty in this stub

    monkeypatch.setattr(pg, "http_get_json", fake_get)
    out = pg.discover_postings("AI internships")
    by_company = {p["company"]: p for p in out}
    assert by_company["Acme AI"]["submit_method"] == "form"
    assert by_company["Acme AI"]["ats"] == "greenhouse"
    assert by_company["Acme AI"]["source"] == "wellfound"
    assert by_company["FinML"]["submit_method"] == "email"
    assert by_company["FinML"]["apply_email"] == "jobs@finml.com"
    assert by_company["FinML"]["source"] == "yc"
    # discovery is data-only: every item has the fields the staging step needs.
    for p in out:
        assert {"track", "source", "company", "role_title", "posting_url",
                "submit_method"} <= set(p)


def test_discover_postings_caps_at_batch_cap(monkeypatch):
    from dispatch.apply import BATCH_CAP

    def fake_get(url, *, params=None, headers=None, timeout=None):
        if "wellfound" in url:
            return {"jobs": [
                {"company": f"C{i}", "title": "AI Intern", "location": "Remote",
                 "url": f"https://jobs.lever.co/c{i}/x", "track": "swe"}
                for i in range(BATCH_CAP + 5)
            ]}
        return {"jobs": []}

    monkeypatch.setattr(pg, "http_get_json", fake_get)
    out = pg.discover_postings()
    assert len(out) <= BATCH_CAP
