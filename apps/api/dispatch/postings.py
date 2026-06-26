"""Job-board discovery (spec §2) — find AI SWE/finance internship postings on
Wellfound, YC "Work at a Startup", and company career pages (the startup/AI-dense,
fetch-friendly boards; LinkedIn/Workday come later). Fetch goes through
http_get_json (the monkeypatchable seam — stubbed in tests, no real network).

This is data-only: it normalizes postings and classifies how each is applied to
(email | form | external). It NEVER sends or submits — submission is gated on
Bo's approval tap in dispatch.apply. classify_submit is honest about brittleness:
Greenhouse/Lever are semi-standard forms (auto-fillable), Workday + captcha/SSO
route to 'external' (prepare + hand off).
"""
from __future__ import annotations

from typing import Optional

from integrations.base import http_get_json
from dispatch.apply import BATCH_CAP

BOARDS = ("wellfound", "yc", "career_page")

# Board endpoints. Real queries are tuned per board; tests stub http_get_json so
# the exact URLs only need to be distinguishable per source.
_BOARD_URLS = {
    "wellfound": "https://wellfound.com/api/jobs/search",
    "yc": "https://www.ycombinator.com/api/jobs",
    "career_page": "https://example.invalid/career_page",  # seeded list slots in later
}

# Form ATSes we can auto-fill (semi-standard). Everything else → external.
_FORM_ATS = {
    "boards.greenhouse.io": "greenhouse",
    "jobs.lever.co": "lever",
}


def classify_submit(posting: dict) -> tuple[str, Optional[str]]:
    """Decide how this posting is applied to. captcha/SSO/Workday → external
    (prepare + hand off, no auto-fill). Greenhouse/Lever → form (auto-fill, human
    submit). An apply_email → email (reuse Phase 1 send)."""
    url = (posting.get("posting_url") or posting.get("url") or "").lower()
    if posting.get("captcha"):
        return ("external", posting.get("ats"))
    if posting.get("apply_email"):
        return ("email", None)
    for host, ats in _FORM_ATS.items():
        if host in url:
            return ("form", ats)
    if "workday" in url or posting.get("ats") == "workday":
        return ("external", "workday")
    return ("external", None)


def _normalize(raw: dict, source: str) -> dict:
    url = raw.get("url") or raw.get("posting_url") or ""
    item = {
        "track": raw.get("track", "swe"),
        "source": source,
        "company": raw.get("company", ""),
        "role_title": raw.get("title") or raw.get("role_title") or "",
        "location": raw.get("location"),
        "posting_url": url,
        "apply_email": raw.get("apply_email"),
    }
    method, ats = classify_submit({**item, "captcha": raw.get("captcha")})
    item["submit_method"] = method
    item["ats"] = ats
    return item


def discover_postings(criteria: str = "") -> list[dict]:
    """Fetch each board, normalize + classify postings, return up to BATCH_CAP.
    Data-only — never sends or submits. A board that errors yields no rows for
    that board (caught) rather than failing the whole batch."""
    out: list[dict] = []
    for source in BOARDS:
        url = _BOARD_URLS[source]
        try:
            raw = http_get_json(url, params={"q": criteria or "AI internship"})
        except Exception:
            continue  # fail-closed per board; no silent global failure
        for job in (raw or {}).get("jobs", []) or []:
            item = _normalize(job, source)
            if item["company"] and item["posting_url"]:
                out.append(item)
            if len(out) >= BATCH_CAP:
                return out
    return out[:BATCH_CAP]
