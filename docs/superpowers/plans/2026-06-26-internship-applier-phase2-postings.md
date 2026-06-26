> For agentic workers: use superpowers:subagent-driven-development or executing-plans

**Goal:** Build Phase 2 (job-board postings + application-form auto-fill) of the internship cold-applier, on top of the shipped Phase 1. Discover job-board postings (Wellfound / YC "Work at a Startup" / company career pages first), prepare a cover letter + common-question answers via the `applier` agent, stage each as a `PostingApplication(status="proposed")`, and surface a per-posting approval Card. On Bo's approval tap only: `submit_method="email"` postings reuse Phase 1's `outlook.send_mail` (user-initiated); `submit_method="form"` postings use a `BrowserFiller` that fills the form then **STOPS before the final submit** (human-submit gate — Bo clicks submit himself); `submit_method="external"` (Workday / captcha / SSO) routes to prepare-and-handoff (a deep link + the prepared text, no auto-fill). Postings fold into the existing `apply:` command and the weekly cron — a batch mixes cold-email targets and postings, each its own card. Spec: `/Users/clawd/borina-mesh/docs/superpowers/specs/2026-06-26-internship-cold-applier-design.md`.

**Architecture:** Mirror the existing mesh exactly. The `PostingApplication` SQLModel mirrors `OutreachItem` (Phase 1) and auto-creates via `init_db`'s `create_all` — no migration. Board discovery lives in a new `dispatch/postings.py` (kept separate from `dispatch/apply.py` per the spec's "or a `dispatch/postings.py`" note) and fetches with `integrations.base.http_get_json` (the same monkeypatchable seam every integration uses — stubbed in tests, no real network). The prepare step calls the `applier` agent via `agents.runner_v2.run_agent_task` (no API key), exactly like Phase 1's `draft_email`. The submit step branches on `submit_method`: `email` reuses the Phase-1 `outlook.send_mail` user-initiated gate; `form` extends the Phase-1 transport seam with a `BrowserFiller` class in `integrations/outlook.py` that exposes `.fill(...)` (fills, never submits) — a real Playwright driver is wired in only when Phase 0 chose browser transport; `external` returns a handoff payload. The approval Card + `apply:submit:{id}` / `apply:open:{id}` callbacks mirror the Phase-1 `apply:send` / `apply:skip` callbacks and the operator/goal callbacks in `routes/telegram.py`. Postings ride the same `apply:` command branch and the same `register_apply_weekly` cron as Phase 1.

**Tech Stack:** Python 3.11 / FastAPI / SQLModel.

## Global Constraints

- **Python 3.11 / FastAPI / SQLModel.**
- **Tests run with:** `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest`
- **Hermetic conftest:** `apps/api/conftest.py` already redirects `DATABASE_URL`, `REPORTS_DIR`, and `GOOGLE_OAUTH_TOKEN_FILE` to throwaway temp paths and seeds the schema via `init_db()`. Board fetches are stubbed by monkeypatching the module-level `http_get_json` reference imported into `dispatch/postings.py`; the browser form-fill is stubbed by monkeypatching `outlook.BrowserFiller.fill`. NEVER touch `~/.borina`, never hit the real network or a real browser.
- **Agents run via the claude CLI** through `agents.runner_v2.run_agent_task` — **NO API key** in code. The Phase-2 prepare step reuses the already-registered `applier` agent (`run_agent_task("applier", prompt)`); never hardcode a key, never register a second agent.
- **SAFETY INVARIANT:** the only outbound paths (`outlook.send_mail` / form-submit) MUST require `user_initiated=True` and be reachable only from Bo's approval tap. The pipeline (discover/prepare/stage) and the agent are text/data-only and MUST NEVER call a send/submit path. `send_mail` already refuses (`not_connected`) when `user_initiated` is False (Phase 1). `BrowserFiller.fill` is best-effort fill that **STOPS before the final submit** — there is no auto-submit code path in Phase 2; the human clicks submit. `external` postings never auto-fill.
- **New tables auto-create** via `init_db`'s `SQLModel.metadata.create_all`. Define `PostingApplication` in `models.py`; conftest's `_init_test_db` imports `models` before `create_all`, so the table exists in tests with no manual migration.
- **Consume Phase 1 EXACTLY — do not redefine:** `models.OutreachItem`; `integrations.outlook.send_mail(recipients, subject, body, *, attachments=None, user_initiated=False, send_via=None) -> IntegrationResult` (data `{"id","via"}`), `outlook.GraphSender` / `outlook.BrowserSender` / `outlook._sender`; `integrations.microsoft_oauth`; `integrations.contacts.find_contact`; the `applier` agent (`run_agent_task("applier", prompt)`); `dispatch.apply.{discover, draft_email, run_apply, get_proposed, approve_send, skip_item, _dedup_key, BATCH_CAP, DAILY_SEND_CAP, DEFAULT_TRACKS}`; `routes/telegram.py`'s `apply_card` / `send_apply_cards` / `_handle_apply_callback` / `_APPLY_RE` / the `apply:` `process_update` branch; `scheduler.register_apply_weekly` / `_run_apply_weekly`. Phase 2 EXTENDS these (new functions, new callback verbs, new card builder) — it never rewrites their signatures.
- **DRY / YAGNI / TDD:** write the failing test first, run it (expect FAIL), implement the minimum real code, run it (expect PASS), commit. No placeholders.

---

## Task 2.1 — `PostingApplication` SQLModel table

The Phase 2 staging table for job-board postings. Auto-creates via `init_db`'s `create_all`; conftest imports `models` before `create_all` so the table exists in tests. Mirrors `OutreachItem`'s stage-then-approve lifecycle with posting-specific fields.

**Files:**
- Modify: `/Users/clawd/borina-mesh/apps/api/models.py`
- Create: `/Users/clawd/borina-mesh/apps/api/tests/test_posting_model.py`

**Interfaces:**
- Consumes: `sqlmodel.{SQLModel, Field}`, `datetime` (already imported in `models.py`).
- Produces `class PostingApplication(SQLModel, table=True)` with fields:
  `id: Optional[int]` (pk); `track: str`; `source: str`; `company: str`; `role_title: str`; `location: Optional[str] = None`; `posting_url: str` (indexed); `submit_method: str`; `ats: Optional[str] = None`; `cover_letter: Optional[str] = None`; `answers_json: str = "{}"`; `status: str = "proposed"` (indexed); `dedup_key: str` (indexed); `error: Optional[str] = None`; `created_at: datetime` (indexed, default `utcnow`); `submitted_at: Optional[datetime] = None`.

**Steps:**

- [ ] Write the failing test. Create `/Users/clawd/borina-mesh/apps/api/tests/test_posting_model.py`:

```python
"""PostingApplication staging table (Phase 2). Auto-created by init_db's
create_all — no migration. Defaults: status='proposed', answers_json='{}',
timestamps. Mirrors test_outreach_model."""
from datetime import datetime

from sqlmodel import select

from db import session_scope
from models import PostingApplication


def test_posting_defaults_and_persist():
    with session_scope() as s:
        item = PostingApplication(
            track="swe", source="wellfound", company="Acme AI",
            role_title="AI Engineering Intern", posting_url="https://wellfound.com/jobs/1",
            submit_method="form", dedup_key="acme ai|ai engineering intern",
        )
        s.add(item)
        s.commit()
        s.refresh(item)
        assert item.id is not None
        assert item.status == "proposed"
        assert item.answers_json == "{}"
        assert item.cover_letter is None and item.submitted_at is None
        assert item.ats is None and item.location is None
        assert isinstance(item.created_at, datetime)


def test_posting_queryable_by_dedup_key():
    with session_scope() as s:
        s.add(PostingApplication(
            track="finance", source="yc", company="FinML",
            role_title="Quant Intern", posting_url="https://yc.example/job/2",
            submit_method="email", dedup_key="finml|quant intern"))
        s.commit()
        rows = s.exec(
            select(PostingApplication).where(
                PostingApplication.dedup_key == "finml|quant intern")
        ).all()
        assert len(rows) == 1 and rows[0].company == "FinML"
```

- [ ] Run it (expect FAIL — model does not exist):
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest tests/test_posting_model.py -q`
  Expected: collection error `ImportError: cannot import name 'PostingApplication' from 'models'`.

- [ ] Minimal implementation. Append to `/Users/clawd/borina-mesh/apps/api/models.py` (after `OutreachItem`, which Phase 1 added at the end of the file):

```python
class PostingApplication(SQLModel, table=True):
    """A staged job-board posting application (Phase 2). NEVER auto-submitted —
    a submit only happens when Bo approves this item via Telegram (the
    user-initiated action). submit_method routes the act: "email" reuses
    outlook.send_mail; "form" uses BrowserFiller (fills, human submits);
    "external" hands Bo a deep link + prepared text. status: proposed | prepared
    | submitted | skipped | failed. Mirrors OutreachItem's lifecycle. Auto-created
    by init_db's create_all."""
    id: Optional[int] = Field(default=None, primary_key=True)
    track: str                                    # "swe" | "finance"
    source: str                                   # "wellfound" | "yc" | "career_page" | "clnx" | ...
    company: str
    role_title: str
    location: Optional[str] = None
    posting_url: str = Field(index=True)
    submit_method: str                            # "email" | "form" | "external"
    ats: Optional[str] = None                     # "greenhouse" | "lever" | "workday" | None
    cover_letter: Optional[str] = None
    answers_json: str = "{}"                       # common-question answers (JSON object)
    status: str = Field(default="proposed", index=True)
    dedup_key: str = Field(index=True)            # normalized company + role_title
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    submitted_at: Optional[datetime] = None
```

- [ ] Run it (expect PASS):
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest tests/test_posting_model.py -q`
  Expected: `2 passed`.

- [ ] Commit:
  `cd /Users/clawd/borina-mesh && git add apps/api/models.py apps/api/tests/test_posting_model.py && git commit -m "Phase 2: PostingApplication staging table"`

---

## Task 2.2 — `BrowserFiller` (fills then STOPS before submit) in `integrations/outlook.py`

Extend the Phase-1 transport seam with a `BrowserFiller` class: a best-effort form filler that fills name/email/resume/cover/answers in Bo's logged-in browser and **STOPS before the final submit** — the human submits. There is NO auto-submit code path. In tests `BrowserFiller.fill` is stubbed; the real Playwright driver is wired in only if Phase 0 picked browser transport. Mirrors `BrowserSender`'s "stubbed in tests, raises until wired" posture but for forms, and is NOT gated on `user_initiated` itself because it does not submit — the gate lives at the submit decision in the pipeline.

**Files:**
- Modify: `/Users/clawd/borina-mesh/apps/api/integrations/outlook.py`
- Create: `/Users/clawd/borina-mesh/apps/api/tests/test_browser_filler.py`

**Interfaces:**
- Consumes: nothing new (same module).
- Produces:
  - `class BrowserFiller` with class attr `via = "browser"` and method
    `fill(self, posting_url: str, fields: dict, *, resume_path: Optional[str] = None) -> dict` — fills the form, STOPS before submit, returns `{"filled": True, "submitted": False, "review_url": str}`. The default (unwired) implementation raises `RuntimeError` so a misconfig fails closed.

**Steps:**

- [ ] Write the failing test. Create `/Users/clawd/borina-mesh/apps/api/tests/test_browser_filler.py`:

```python
"""BrowserFiller (Phase 2): fills a form then STOPS before the final submit —
the human-submit gate. There is no auto-submit path. Stubbed in tests (no real
browser). Mirrors BrowserSender's unwired-raises posture."""
import pytest

from integrations import outlook


def test_browser_filler_unwired_raises():
    # Default (no Playwright driver wired) fails closed — never silently
    # pretends to have filled a form.
    with pytest.raises(RuntimeError):
        outlook.BrowserFiller().fill("https://boards.greenhouse.io/x/jobs/1", {"name": "Bo"})


def test_browser_filler_fill_never_reports_submitted(monkeypatch):
    # When wired (stubbed here), fill returns submitted=False — it stops before
    # the final submit so Bo clicks it himself.
    def fake_fill(self, posting_url, fields, *, resume_path=None):
        return {"filled": True, "submitted": False, "review_url": posting_url}

    monkeypatch.setattr(outlook.BrowserFiller, "fill", fake_fill)
    res = outlook.BrowserFiller().fill(
        "https://jobs.lever.co/acme/1", {"name": "Bo", "email": "bo@x.com"},
        resume_path="/tmp/resume.pdf",
    )
    assert res["filled"] is True
    assert res["submitted"] is False
    assert res["review_url"].endswith("/1")


def test_browser_filler_via_marker():
    assert outlook.BrowserFiller.via == "browser"
```

- [ ] Run it (expect FAIL — class does not exist):
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest tests/test_browser_filler.py -q`
  Expected: `AttributeError: module 'integrations.outlook' has no attribute 'BrowserFiller'`.

- [ ] Minimal implementation. In `/Users/clawd/borina-mesh/apps/api/integrations/outlook.py`, add the `BrowserFiller` class after `BrowserSender` (before `_sender`):

```python
class BrowserFiller:
    """Playwright-driven application-form filler (Phase 2 — form postings).

    SAFETY: this fills name/email/resume-upload/cover/answers in Bo's logged-in
    browser and then STOPS before the final submit — Bo reviews and clicks submit
    himself (the human-submit gate). There is deliberately NO auto-submit code
    path here. Stubbed in tests; the real Playwright driver is wired in only if
    Phase 0 chose the browser transport. Unwired it fails closed (raises) so a
    misconfig never silently claims a form was filled."""

    via = "browser"

    def fill(self, posting_url: str, fields: dict, *,
             resume_path: Optional[str] = None) -> dict:
        raise RuntimeError(
            "browser form-fill not wired — set up the Playwright driver "
            "(OUTLOOK_SEND_TRANSPORT=browser) on the Mini"
        )
```

- [ ] Run it (expect PASS):
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest tests/test_browser_filler.py -q`
  Expected: `3 passed`.

- [ ] Commit:
  `cd /Users/clawd/borina-mesh && git add apps/api/integrations/outlook.py apps/api/tests/test_browser_filler.py && git commit -m "Phase 2: BrowserFiller (fills then stops before submit; human-submit gate)"`

---

## Task 2.3 — `dispatch/postings.py` board discovery (Wellfound / YC / career pages first; web-fetch + parse, stubbed)

Board discovery: query Wellfound, YC "Work at a Startup", and company career pages for AI SWE/finance internships (Toronto/remote), parse the results into normalized candidates, and classify each posting's `submit_method` + `ats`. Fetch goes through `http_get_json` (the monkeypatchable seam — stubbed in tests, no real network). Text/data only — never sends or submits. Mirrors `dispatch.apply.discover`'s "deterministic now, live fetch slots in later" shape but split into source fetchers.

**Files:**
- Create: `/Users/clawd/borina-mesh/apps/api/dispatch/postings.py`
- Create: `/Users/clawd/borina-mesh/apps/api/tests/test_postings_discover.py`

**Interfaces:**
- Consumes: `integrations.base.http_get_json` (imported module-level so tests can monkeypatch `postings.http_get_json`).
- Produces:
  - `BOARDS = ("wellfound", "yc", "career_page")` — priority order (spec: startup/AI-dense, friendly to fetch, before LinkedIn/Workday).
  - `def classify_submit(posting: dict) -> tuple[str, Optional[str]]` — returns `(submit_method, ats)`. `apply_email` present → `("email", None)`; Greenhouse/Lever apply URL → `("form", "greenhouse"|"lever")`; Workday URL / `ats=="workday"` / captcha flag → `("external", ats)`; otherwise `("external", None)`.
  - `def discover_postings(criteria: str = "") -> list[dict]` — fetches each board, normalizes, classifies, returns `[{track, source, company, role_title, location, posting_url, submit_method, ats, apply_email}]` (each item carries the optional `apply_email` for the email-submit path). Drops nothing silently; capped at `dispatch.apply.BATCH_CAP`.

**Steps:**

- [ ] Write the failing test. Create `/Users/clawd/borina-mesh/apps/api/tests/test_postings_discover.py`:

```python
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
```

- [ ] Run it (expect FAIL — module does not exist):
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest tests/test_postings_discover.py -q`
  Expected: collection error `ModuleNotFoundError: No module named 'dispatch.postings'`.

- [ ] Minimal implementation. Create `/Users/clawd/borina-mesh/apps/api/dispatch/postings.py`:

```python
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
```

- [ ] Run it (expect PASS):
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest tests/test_postings_discover.py -q`
  Expected: `7 passed`.

- [ ] Commit:
  `cd /Users/clawd/borina-mesh && git add apps/api/dispatch/postings.py apps/api/tests/test_postings_discover.py && git commit -m "Phase 2: dispatch/postings board discovery (Wellfound/YC/career pages; classify email/form/external)"`

---

## Task 2.4 — Posting pipeline in `dispatch/apply.py` (prepare → stage; staging NEVER submits)

Extend `dispatch/apply.py` (not `postings.py`, so the approval surface has one home) with the posting pipeline: `prepare_posting` has the `applier` agent write a cover letter + common-question answers (text only); `run_postings` discovers via `dispatch.postings.discover_postings`, prepares, and stages `PostingApplication(status="proposed")` — it NEVER submits. `get_proposed_postings` lists them. `submit_posting` is the ONLY submit path, gated on Bo's approval tap: `email` → `outlook.send_mail(user_initiated=True)`; `form` → `BrowserFiller().fill(...)` (fills, stops before submit) → status `prepared` with a review link; `external` → returns a handoff payload, status `prepared`. `skip_posting` flips `skipped`. Mirrors Phase 1's `run_apply` / `approve_send` / `skip_item` exactly.

**Files:**
- Modify: `/Users/clawd/borina-mesh/apps/api/dispatch/apply.py`
- Create: `/Users/clawd/borina-mesh/apps/api/tests/test_postings_pipeline.py`

**Interfaces:**
- Consumes: `db.session_scope`, `models.PostingApplication`, `dispatch.postings.discover_postings`, `agents.runner_v2.run_agent_task`, `integrations.outlook.{send_mail, BrowserFiller}`, `json`, `dispatch.apply._dedup_key`.
- Produces (added to `dispatch/apply.py`):
  - `def _posting_dedup_key(company: str, role_title: str) -> str`
  - `async def prepare_posting(posting: dict) -> dict` — `{"cover_letter": str, "answers": dict}` (text-only, applier agent; deterministic fallback).
  - `async def run_postings(criteria: str = "", chat_id: Optional[int] = None) -> dict` — discovers → prepares → STAGES; returns `{"staged": int, "dropped": int, "item_ids": list[int], "reasons": list[str]}`. NEVER submits.
  - `def get_proposed_postings() -> list[dict]`
  - `def submit_posting(item_id: int) -> dict` — the ONLY submit path. email→`{"status":"submitted","method":"email","company"}`; form→`{"status":"prepared","method":"form","review_url"}`; external→`{"status":"prepared","method":"external","handoff":{...}}`; failure→`{"status":"failed","error"}`; non-proposed→`{"status":..., "already_decided":True}`.
  - `def skip_posting(item_id: int) -> dict`
- Also: extend `run_apply` to also stage postings so the `apply:` command + cron cover both (Task 2.6).

**Steps:**

- [ ] Write the failing test. Create `/Users/clawd/borina-mesh/apps/api/tests/test_postings_pipeline.py`:

```python
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
```

- [ ] Run it (expect FAIL — functions missing):
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest tests/test_postings_pipeline.py -q`
  Expected: `AttributeError: module 'dispatch.apply' has no attribute 'run_postings'`.

- [ ] Minimal implementation. In `/Users/clawd/borina-mesh/apps/api/dispatch/apply.py`, add `import json` to the top imports (after `from datetime import datetime`), then append the posting pipeline after `skip_item` (the last Phase-1 function):

```python
def _posting_dedup_key(company: str, role_title: str) -> str:
    return f"{(company or '').strip().lower()}|{(role_title or '').strip().lower()}"


async def prepare_posting(posting: dict) -> dict:
    """Have the applier agent tailor a cover letter + common-question answers for
    one posting. Text-only — never submits. Falls back to a deterministic draft if
    the agent CLI yields nothing (hermetic tests stub this entirely)."""
    from agents.runner_v2 import run_agent_task

    prompt = (
        f"Prepare an internship application.\n"
        f"Company: {posting['company']}\nRole: {posting['role_title']}\n"
        f"Location: {posting.get('location')}\nTrack: {posting['track']}\n"
        f"Posting: {posting.get('posting_url')}\n"
        f"Write a short, specific cover letter (reference the company's actual AI "
        f"work, tie it to Bo's profile, name the track), then answer the common "
        f"question 'Why do you want to work here?'. Output the cover letter first, "
        f"then a line 'WHY: ' with the answer."
    )
    result = await run_agent_task("applier", prompt)
    text = (getattr(result, "output", "") or "").strip()
    cover = text
    why = ""
    for line in text.splitlines():
        if line.upper().startswith("WHY:"):
            why = line.split(":", 1)[1].strip()
            cover = text.split(line, 1)[0].strip()
            break
    if not cover:
        cover = (f"Dear {posting['company']} team, I'm Bo — a business student "
                 f"focused on {posting['track']} + AI. I'm excited by your work and "
                 f"would love to intern on {posting['role_title']}.")
    if not why:
        why = f"I admire {posting['company']}'s AI work and want to contribute as an intern."
    return {"cover_letter": cover, "answers": {"why": why}}


async def run_postings(criteria: str = "", chat_id: Optional[int] = None) -> dict:
    """Discover postings → prepare cover/answers → STAGE. Never submits. Dropped
    (deduped) postings are counted + reasoned. Returns a batch summary."""
    from dispatch.postings import discover_postings

    found = discover_postings(criteria)
    with session_scope() as s:
        existing = {r.dedup_key for r in s.exec(select(PostingApplication)).all()}

    item_ids: list[int] = []
    dropped = 0
    reasons: list[str] = []

    for post in found:
        key = _posting_dedup_key(post["company"], post["role_title"])
        if key in existing:
            dropped += 1
            reasons.append(f"{post['company']} {post['role_title']}: dedup (already staged)")
            continue
        prep = await prepare_posting(post)
        with session_scope() as s:
            item = PostingApplication(
                track=post["track"], source=post["source"], company=post["company"],
                role_title=post["role_title"], location=post.get("location"),
                posting_url=post["posting_url"], submit_method=post["submit_method"],
                ats=post.get("ats"), cover_letter=prep["cover_letter"],
                answers_json=json.dumps(prep["answers"]), dedup_key=key,
            )
            # Stash the apply_email on a non-column attr? No — email lives in the
            # posting; persist it into the cover-letter prep is wrong. We store the
            # recipient in answers_json under a reserved key so the submit step has
            # it without a new column.
            answers = dict(prep["answers"])
            if post.get("apply_email"):
                answers["_apply_email"] = post["apply_email"]
            item.answers_json = json.dumps(answers)
            s.add(item)
            s.commit()
            s.refresh(item)
            item_ids.append(item.id)
        existing.add(key)

    return {"staged": len(item_ids), "dropped": dropped,
            "item_ids": item_ids, "reasons": reasons}


def get_proposed_postings() -> list[dict]:
    with session_scope() as s:
        rows = s.exec(
            select(PostingApplication).where(PostingApplication.status == "proposed")
            .order_by(PostingApplication.created_at)
        ).all()
        return [
            {"id": r.id, "track": r.track, "source": r.source, "company": r.company,
             "role_title": r.role_title, "location": r.location,
             "posting_url": r.posting_url, "submit_method": r.submit_method,
             "ats": r.ats, "cover_letter": r.cover_letter}
            for r in rows
        ]


def submit_posting(item_id: int) -> dict:
    """The ONLY submit path — invoked solely by Bo's Telegram approval tap.

    email   → outlook.send_mail(user_initiated=True); status 'submitted'.
    form    → BrowserFiller fills then STOPS before submit; status 'prepared',
              returns a review_url so Bo opens it and clicks submit himself.
    external→ no auto-fill; returns a handoff (deep link + prepared text);
              status 'prepared'.
    Idempotent: a non-proposed item is a no-op. A failed act stays 'failed'
    (retryable), never silently lost."""
    from integrations import outlook

    with session_scope() as s:
        item = s.get(PostingApplication, item_id)
        if not item:
            raise KeyError("posting application not found")
        if item.status != "proposed":
            return {"status": item.status, "already_decided": True}

        answers = json.loads(item.answers_json or "{}")
        try:
            if item.submit_method == "email":
                recipient = answers.get("_apply_email")
                if not recipient:
                    item.status = "failed"
                    item.error = "no apply email on posting"
                    s.add(item)
                    s.commit()
                    return {"status": "failed", "error": item.error}
                res = outlook.send_mail(
                    [recipient], f"Application — {item.role_title} ({item.company})",
                    item.cover_letter or "", user_initiated=True,
                )
                if res.connected:
                    item.status = "submitted"
                    item.submitted_at = datetime.utcnow()
                    item.error = None
                    s.add(item)
                    s.commit()
                    return {"status": "submitted", "method": "email", "company": item.company}
                item.status = "failed"
                item.error = res.error
                s.add(item)
                s.commit()
                return {"status": "failed", "error": item.error}

            if item.submit_method == "form":
                fields = {"cover_letter": item.cover_letter or "", **{
                    k: v for k, v in answers.items() if not k.startswith("_")}}
                filled = outlook.BrowserFiller().fill(item.posting_url, fields)
                # fill STOPS before submit → status 'prepared', Bo submits.
                item.status = "prepared"
                item.error = None
                s.add(item)
                s.commit()
                return {"status": "prepared", "method": "form",
                        "review_url": filled.get("review_url", item.posting_url)}

            # external (Workday / captcha / SSO) — no auto-fill, hand off.
            item.status = "prepared"
            item.error = None
            s.add(item)
            s.commit()
            return {"status": "prepared", "method": "external", "handoff": {
                "posting_url": item.posting_url,
                "cover_letter": item.cover_letter,
                "answers": {k: v for k, v in answers.items() if not k.startswith("_")},
            }}
        except Exception as exc:  # noqa: BLE001 — fail-closed, retryable
            item.status = "failed"
            item.error = f"{type(exc).__name__}: {exc}"
            s.add(item)
            s.commit()
            return {"status": "failed", "error": item.error}


def skip_posting(item_id: int) -> dict:
    """Mark a staged posting skipped. Submits/sends nothing."""
    with session_scope() as s:
        item = s.get(PostingApplication, item_id)
        if not item:
            raise KeyError("posting application not found")
        if item.status == "proposed":
            item.status = "skipped"
            s.add(item)
            s.commit()
        return {"status": item.status}
```

  Also add the `PostingApplication` import at the top of `dispatch/apply.py` (the Phase-1 line `from models import OutreachItem` becomes):

```python
from models import OutreachItem, PostingApplication
```

- [ ] Run it (expect PASS):
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest tests/test_postings_pipeline.py -q`
  Expected: `7 passed`.

- [ ] Commit:
  `cd /Users/clawd/borina-mesh && git add apps/api/dispatch/apply.py apps/api/tests/test_postings_pipeline.py && git commit -m "Phase 2: posting pipeline (prepare→stage; staging never submits; email/form/external submit)"`

---

## Task 2.5 — Posting approval Card + `apply:submit`/`apply:open` callbacks (`routes/telegram.py`)

The posting approval surface. A Card per staged `PostingApplication` with `[Submit, Skip, Open]` buttons; `apply:submit:{id}` is Bo's user-initiated tap that calls `submit_posting`; `apply:skip:{id}` already exists (Phase 1 verb) but here routes to `skip_posting` — so the callback handler must disambiguate outreach vs posting by id namespace. To keep callback parsing unambiguous and within 64 bytes, posting verbs use a `p` marker: `apply:submit:{id}`, `apply:pskip:{id}`, `apply:open:{id}`. Mirrors the Phase-1 `_handle_apply_callback` extension and the operator/goal callbacks.

**Files:**
- Modify: `/Users/clawd/borina-mesh/apps/api/routes/telegram.py`
- Create: `/Users/clawd/borina-mesh/apps/api/tests/test_postings_telegram.py`

**Interfaces:**
- Consumes: `dispatch.apply.{get_proposed_postings, submit_posting, skip_posting}`, `dispatch.cards.{Card, Action, send_card}`.
- Produces (added to `routes/telegram.py`):
  - `posting_card(item: dict) -> Card` (verbs `apply:submit:{id}`, `apply:pskip:{id}`, `apply:open:{id}`).
  - `send_posting_cards(chat_id: int) -> int`.
  - Extend `_handle_apply_callback` to handle `submit`, `pskip`, `open` verbs (in addition to Phase-1 `send`/`skip`).

**Steps:**

- [ ] Write the failing test. Create `/Users/clawd/borina-mesh/apps/api/tests/test_postings_telegram.py`:

```python
"""Posting approval surface (Phase 2): a posting card with Submit/Skip/Open; the
apply:submit tap is the user-initiated submit; apply:pskip skips; apply:open
surfaces the link. Mirrors test_apply_telegram."""
import pytest

import routes.telegram as tg
from dispatch import dispatcher
from dispatch import apply as ap


@pytest.fixture(autouse=True)
def _capture(monkeypatch):
    from db import engine
    import fleet_roster as fr
    fr.seed_roster(engine)
    sent = []

    def _fake_send(chat_id, text, reply_markup=None):
        sent.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})
        return 1

    monkeypatch.setattr(dispatcher, "send_telegram_message", _fake_send)
    return sent


def _posting(**over):
    base = {"id": 5, "track": "swe", "source": "wellfound", "company": "Acme AI",
            "role_title": "AI SWE Intern", "location": "Toronto",
            "posting_url": "https://boards.greenhouse.io/acme/jobs/9",
            "submit_method": "form", "ats": "greenhouse",
            "cover_letter": "Dear Acme team, ..."}
    base.update(over)
    return base


def test_posting_card_has_submit_skip_open():
    card = tg.posting_card(_posting())
    datas = [a.data for a in card.actions]
    assert "apply:submit:5" in datas
    assert "apply:pskip:5" in datas
    assert "apply:open:5" in datas


def test_apply_submit_callback_invokes_submit_posting(monkeypatch, _capture):
    calls = []
    monkeypatch.setattr(ap, "submit_posting",
                        lambda i: calls.append(i) or {"status": "prepared", "method": "form",
                                                       "review_url": "https://x/9"})
    res = tg._handle_apply_callback("apply:submit:5", 99)
    assert res["status"] == "apply_submit"
    assert calls == [5]


def test_apply_submit_email_reports_submitted(monkeypatch, _capture):
    monkeypatch.setattr(ap, "submit_posting",
                        lambda i: {"status": "submitted", "method": "email", "company": "FinML"})
    res = tg._handle_apply_callback("apply:submit:7", 99)
    assert res["status"] == "apply_submit"
    assert any("FinML" in m["text"] for m in _capture)


def test_apply_pskip_callback_invokes_skip_posting(monkeypatch, _capture):
    calls = []
    monkeypatch.setattr(ap, "skip_posting", lambda i: calls.append(i) or {"status": "skipped"})
    res = tg._handle_apply_callback("apply:pskip:5", 99)
    assert res["status"] == "apply_pskip"
    assert calls == [5]


def test_apply_open_surfaces_link(monkeypatch, _capture):
    monkeypatch.setattr(ap, "get_proposed_postings", lambda: [_posting()])
    res = tg._handle_apply_callback("apply:open:5", 99)
    assert res["status"] == "apply_open"
    assert any("greenhouse.io" in m["text"] for m in _capture)


def test_handle_callback_routes_submit_prefix(monkeypatch, _capture):
    monkeypatch.setattr(ap, "submit_posting",
                        lambda i: {"status": "prepared", "method": "external",
                                   "handoff": {"posting_url": "u", "cover_letter": "c", "answers": {}}})
    res = tg._handle_callback("apply:submit:3", 99)
    assert res["status"] == "apply_submit"
```

- [ ] Run it (expect FAIL — `posting_card` / submit verb missing):
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest tests/test_postings_telegram.py -q`
  Expected: `AttributeError: module 'routes.telegram' has no attribute 'posting_card'`.

- [ ] Add the posting card builder + cards sender. In `/Users/clawd/borina-mesh/apps/api/routes/telegram.py`, insert after the Phase-1 `send_apply_cards` function:

```python
def posting_card(item: dict) -> "object":
    """Approval card for one staged PostingApplication: Submit / Skip / Open.
    apply:submit:{id} is Bo's user-initiated tap (email→send, form→fill-then-stop,
    external→handoff); apply:pskip:{id} skips; apply:open:{id} surfaces the link."""
    from dispatch.cards import Card, Action

    method = item.get("submit_method", "form")
    note = {"email": "applies by email",
            "form": "auto-fills the form, then YOU submit",
            "external": "prepares text + deep link, you submit"}.get(method, method)
    preview = (item.get("cover_letter") or "")[:160]
    return Card(
        headline=f"{item['company']} — {item['role_title']} ({item['track']})",
        lines=[
            f"Source: {item.get('source')}  Location: {item.get('location') or 'n/a'}",
            f"Apply: {method} — {note}",
            preview,
        ],
        actions=[
            Action("Submit", f"apply:submit:{item['id']}"),
            Action("Skip", f"apply:pskip:{item['id']}"),
            Action("Open", f"apply:open:{item['id']}"),
        ],
        buttons_per_row=3,
    )


def send_posting_cards(chat_id: int) -> int:
    """Post one approval card per proposed PostingApplication. Returns the count."""
    from dispatch.cards import send_card
    from dispatch import apply as apply_mod

    items = apply_mod.get_proposed_postings()
    for it in items:
        send_card(chat_id, posting_card(it))
    return len(items)
```

- [ ] Extend `_handle_apply_callback` to handle the posting verbs. In the existing Phase-1 `_handle_apply_callback`, add the `submit` / `pskip` / `open` branches alongside `send` / `skip` (insert before the final `return {"ok": True, "status": "apply_unknown", "toast": ""}`):

```python
        if verb == "submit":
            res = apply_mod.submit_posting(item_id)
            if res.get("already_decided"):
                return {"ok": True, "status": "apply_submit", "item_id": item_id, "toast": "Already done"}
            method = res.get("method")
            status = res.get("status")
            if status == "submitted":
                msg, toast = f"Applied to {res.get('company')} by email.", "Submitted ✓"
            elif status == "prepared" and method == "form":
                msg = (f"Form filled — review & submit it yourself:\n{res.get('review_url')}")
                toast = "Filled — you submit"
            elif status == "prepared" and method == "external":
                h = res.get("handoff", {})
                msg = (f"Prepared. Apply here yourself:\n{h.get('posting_url')}\n\n"
                       f"Cover letter:\n{h.get('cover_letter')}")
                toast = "Prepared — handoff"
            else:
                msg, toast = (f"Submit failed ({res.get('error')}) — kept it so you can retry."), "Failed"
            dispatcher.send_telegram_message(chat_id, format_telegram(msg))
            return {"ok": True, "status": "apply_submit", "item_id": item_id, "toast": toast}
        if verb == "pskip":
            apply_mod.skip_posting(item_id)
            dispatcher.send_telegram_message(chat_id, format_telegram("Skipped posting."))
            return {"ok": True, "status": "apply_pskip", "item_id": item_id, "toast": "Skipped"}
        if verb == "open":
            match = next((p for p in apply_mod.get_proposed_postings() if p["id"] == item_id), None)
            link = match["posting_url"] if match else "(no link)"
            dispatcher.send_telegram_message(chat_id, format_telegram(f"Posting: {link}"))
            return {"ok": True, "status": "apply_open", "item_id": item_id, "toast": ""}
```

  Note: `apply:submit`/`apply:pskip`/`apply:open` already route through `_handle_apply_callback` because `_handle_callback` dispatches every `apply:`-prefixed callback there (Phase 1's `if action == "apply": return _handle_apply_callback(...)`). No change to `_handle_callback` is needed.

- [ ] Run it (expect PASS):
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest tests/test_postings_telegram.py -q`
  Expected: `6 passed`.

- [ ] Commit:
  `cd /Users/clawd/borina-mesh && git add apps/api/routes/telegram.py apps/api/tests/test_postings_telegram.py && git commit -m "Phase 2: posting approval card + apply:submit/apply:pskip/apply:open callbacks"`

---

## Task 2.6 — Fold postings into the `apply:` command + weekly cron

Postings ride the same `apply:` command and the same `register_apply_weekly` cron as Phase 1 — a batch mixes cold-email targets and postings, each its own card. Extend the Phase-1 `apply:` `process_update` branch to ALSO run `run_postings` + `send_posting_cards`, and extend `_run_apply_weekly` to do the same. Neither path submits. Mirrors how Phase 1's branch already runs `run_apply` + `send_apply_cards`.

**Files:**
- Modify: `/Users/clawd/borina-mesh/apps/api/routes/telegram.py` (the `apply:` `process_update` branch)
- Modify: `/Users/clawd/borina-mesh/apps/api/scheduler.py` (`_run_apply_weekly`)
- Create: `/Users/clawd/borina-mesh/apps/api/tests/test_apply_command_postings.py`

**Interfaces:**
- Consumes: `dispatch.apply.{run_apply, run_postings}`, `routes.telegram.{send_apply_cards, send_posting_cards}`.
- Produces: the extended `apply:` branch returns `{"ok": True, "status": "apply_started", "staged": int, "cards": int, "posting_cards": int}` (postings counted alongside email cards); the extended cron handler posts both card kinds.

**Steps:**

- [ ] Write the failing test. Create `/Users/clawd/borina-mesh/apps/api/tests/test_apply_command_postings.py`:

```python
"""The apply: command + weekly cron cover BOTH cold emails and postings (Phase 2),
each its own card. Neither path submits. Mirrors test_apply_telegram +
test_apply_scheduler."""
import pytest

import routes.telegram as tg
from dispatch import dispatcher
from dispatch import apply as ap


@pytest.fixture(autouse=True)
def _capture(monkeypatch):
    from db import engine
    import fleet_roster as fr
    fr.seed_roster(engine)
    sent = []

    def _fake_send(chat_id, text, reply_markup=None):
        sent.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})
        return 1

    monkeypatch.setattr(dispatcher, "send_telegram_message", _fake_send)
    return sent


def test_apply_command_stages_emails_and_postings(monkeypatch, _capture):
    BO = 6452258223
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", str(BO))

    async def fake_run(criteria="", chat_id=None):
        return {"staged": 1, "dropped": 0, "item_ids": [11], "reasons": []}

    async def fake_postings(criteria="", chat_id=None):
        return {"staged": 1, "dropped": 1, "item_ids": [21],
                "reasons": ["BigCo AI Intern: dedup (already staged)"]}

    monkeypatch.setattr(ap, "run_apply", fake_run)
    monkeypatch.setattr(ap, "run_postings", fake_postings)
    monkeypatch.setattr(ap, "get_proposed", lambda: [
        {"id": 11, "track": "swe", "company": "Acme AI",
         "contact_email": "ada@acme.ai", "subject": "S", "body": "B"}])
    monkeypatch.setattr(ap, "get_proposed_postings", lambda: [
        {"id": 21, "track": "swe", "source": "wellfound", "company": "FinML",
         "role_title": "AI SWE Intern", "location": "Remote",
         "posting_url": "https://boards.greenhouse.io/finml/jobs/1",
         "submit_method": "form", "ats": "greenhouse", "cover_letter": "Dear ..."}])

    update = {"update_id": 1, "message": {"chat": {"id": BO}, "text": "apply: AI internships"}}
    res = tg.process_update(update)
    assert res["status"] == "apply_started"
    datas = [b["callback_data"] for m in _capture if m["reply_markup"]
             for row in m["reply_markup"]["inline_keyboard"] for b in row]
    assert "apply:send:11" in datas      # cold-email card
    assert "apply:submit:21" in datas    # posting card
    # drop counts surfaced (no silent caps)
    assert any("dropped" in m["text"].lower() for m in _capture)


@pytest.mark.asyncio
async def test_weekly_cron_stages_both_without_submitting(monkeypatch):
    from scheduler import SchedulerService
    from integrations import outlook
    from integrations.base import ok

    acted = []
    monkeypatch.setattr(outlook, "send_mail",
                        lambda *a, **k: acted.append("send") or ok("outlook", {"id": "x", "via": "graph"}))
    monkeypatch.setattr(outlook.BrowserFiller, "fill",
                        lambda self, *a, **k: acted.append("fill") or {"filled": True, "submitted": False, "review_url": "u"})

    async def fake_run(criteria="", chat_id=None):
        return {"staged": 1, "dropped": 0, "item_ids": [1], "reasons": []}

    monkeypatch.setattr(ap, "run_apply", fake_run)
    monkeypatch.setattr(ap, "run_postings", fake_run)
    monkeypatch.setattr(ap, "get_proposed", lambda: [])
    monkeypatch.setattr(ap, "get_proposed_postings", lambda: [])
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    svc = SchedulerService()
    await svc._run_apply_weekly()
    assert acted == []  # the cron stages both kinds, submits nothing
```

- [ ] Run it (expect FAIL — branch only stages emails):
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest tests/test_apply_command_postings.py -q`
  Expected: `assert "apply:submit:21" in datas` fails (postings not staged/carded yet).

- [ ] Extend the `apply:` `process_update` branch. In `/Users/clawd/borina-mesh/apps/api/routes/telegram.py`, replace the Phase-1 `apply:` branch body (the block under `am = _APPLY_RE.match(text)` that runs only `run_apply` + `send_apply_cards`) with the both-kinds version:

```python
    # 2b1c. Apply: internship pipeline (propose-only) — covers BOTH cold-email
    # targets and job-board postings. Stage each kind and post one approval card
    # per item. Forbidden-gate exempt like build:/goal: (it stages text; nothing
    # is sent/submitted without Bo's approval tap). Runs the async pipelines to
    # completion here so the cards are posted before we return.
    am = _APPLY_RE.match(text)
    if am:
        import asyncio
        from dispatch import apply as apply_mod

        criteria = (am.group("criteria") or "").strip()
        email_summary = asyncio.run(apply_mod.run_apply(criteria, chat_id))
        posting_summary = asyncio.run(apply_mod.run_postings(criteria, chat_id))
        n_email = send_apply_cards(chat_id)
        n_post = send_posting_cards(chat_id)
        staged = email_summary.get("staged", 0) + posting_summary.get("staged", 0)
        dropped = email_summary.get("dropped", 0) + posting_summary.get("dropped", 0)
        tail = f" ({dropped} dropped)" if dropped else ""
        dispatcher.send_telegram_message(
            chat_id,
            format_telegram(
                f"{heard}Staged {staged} application(s){tail} "
                f"({n_email} email, {n_post} posting). Approve each below."
            ),
        )
        return {"ok": True, "status": "apply_started", "staged": staged,
                "cards": n_email, "posting_cards": n_post}
```

- [ ] Extend the weekly cron handler. In `/Users/clawd/borina-mesh/apps/api/scheduler.py`, replace the body of `_run_apply_weekly` so it stages and cards both kinds (keep the structure; add `run_postings` + `send_posting_cards`):

```python
    async def _run_apply_weekly(self) -> None:
        """Weekly internship batch: stage cold-email drafts AND job-board postings,
        then post approval cards for each. NEVER sends/submits — that stays behind
        Bo's approval tap."""
        try:
            import os
            from dispatch import apply as apply_mod
            email_summary = await apply_mod.run_apply("")
            posting_summary = await apply_mod.run_postings("")
            chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
            if chat:
                from routes.telegram import send_apply_cards, send_posting_cards
                from dispatch import dispatcher
                from dispatch.telegram_format import format_telegram
                n_email = send_apply_cards(int(chat))
                n_post = send_posting_cards(int(chat))
                staged = email_summary.get("staged", 0) + posting_summary.get("staged", 0)
                dropped = email_summary.get("dropped", 0) + posting_summary.get("dropped", 0)
                dispatcher.send_telegram_message(
                    int(chat),
                    format_telegram(
                        f"Weekly applier: staged {staged} application(s) "
                        f"({n_email} email, {n_post} posting), {dropped} dropped. "
                        f"Approve each with the buttons."
                    ),
                )
                print(f"[scheduler] apply-weekly: {n_email + n_post} card(s)")
            else:
                staged = email_summary.get("staged", 0) + posting_summary.get("staged", 0)
                print(f"[scheduler] apply-weekly: staged {staged} (no chat configured)")
        except Exception as e:
            print(f"[scheduler] apply-weekly error: {e}")
```

- [ ] Run it (expect PASS):
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest tests/test_apply_command_postings.py -q`
  Expected: `2 passed`.

- [ ] Run the Phase-1 apply tests to confirm no regression in the command/cron they shipped:
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest tests/test_apply_telegram.py tests/test_apply_scheduler.py -q`
  Expected: all pass (the Phase-1 `apply:` command test still gets its `apply:send:11`; `run_postings`/`get_proposed_postings` return empty in those tests since `PostingApplication` is empty and discovery is unstubbed → an empty board fetch via the `http_get_json` seam against `example.invalid` raises and is caught → 0 postings, 0 cards). If a Phase-1 test now fails, the cron/command change broke it — fix before continuing.

- [ ] Commit:
  `cd /Users/clawd/borina-mesh && git add apps/api/routes/telegram.py apps/api/scheduler.py apps/api/tests/test_apply_command_postings.py && git commit -m "Phase 2: fold postings into apply: command + weekly cron (mixed batch; never submits)"`

---

## Final self-review checklist

- [ ] **Safety invariant — no autonomous submit/send.** Staging never submits (test_postings_pipeline: `test_run_postings_stages_and_never_submits`). The `apply:` command and weekly cron stage both kinds and never act (test_apply_command_postings: `test_apply_command_stages_emails_and_postings`, `test_weekly_cron_stages_both_without_submitting`). `outlook.send_mail` still refuses without `user_initiated` (Phase 1, unchanged).
- [ ] **Only Bo's tap submits.** `apply:submit:{id}` → `submit_posting`: email reuses `send_mail(user_initiated=True)` exactly once and is idempotent (test_postings_pipeline: `test_submit_email_posting_is_user_initiated`); the verb is wired through `_handle_apply_callback` (test_postings_telegram: `test_apply_submit_callback_invokes_submit_posting`, `test_handle_callback_routes_submit_prefix`). `apply:pskip` submits nothing (`test_skip_posting_does_nothing`).
- [ ] **Human-submit gate for forms.** `BrowserFiller.fill` returns `submitted=False`; the form path leaves status `prepared` and hands Bo a `review_url` to submit himself — there is no auto-submit code path (test_browser_filler: `test_browser_filler_fill_never_reports_submitted`; test_postings_pipeline: `test_submit_form_posting_fills_but_does_not_submit`).
- [ ] **Workday/captcha route to external.** `classify_submit` sends Workday + captcha to `external`; `submit_posting` external returns a handoff (deep link + prepared text), never auto-fills (test_postings_discover: `test_classify_workday_is_external`, `test_classify_captcha_is_external`; test_postings_pipeline: `test_submit_external_posting_hands_off`).
- [ ] **Email-postings reuse Phase 1.** The `email` branch calls `integrations.outlook.send_mail` with `user_initiated=True` and the posting's `_apply_email` recipient — the Phase-1 signature, unchanged (test_postings_pipeline: `test_submit_email_posting_is_user_initiated`).
- [ ] **Fail-closed externals.** A board fetch error yields no rows for that board, not a global failure (postings `discover_postings` per-board `try/except`). A form-fill failure leaves status `failed` + error, retryable (test_postings_pipeline: `test_submit_form_fill_failure_stays_retryable`). `BrowserFiller` unwired raises (test_browser_filler: `test_browser_filler_unwired_raises`).
- [ ] **No silent caps.** Dedup drops are counted + reasoned in the summary and surfaced in the command reply (test_postings_pipeline: `test_postings_dedup`; test_apply_command_postings: drop count assertion). Discovery caps at `BATCH_CAP` (test_postings_discover: `test_discover_postings_caps_at_batch_cap`).
- [ ] **Phase 1 consumed, not redefined.** Reuses `outlook.send_mail` (+ its gate), `BrowserFiller` extends the transport seam, `run_agent_task("applier", ...)`, `dispatch.apply._dedup_key`/`BATCH_CAP`, the `apply:` command + `_handle_apply_callback` + `apply:` callback routing, and `register_apply_weekly`. No Phase-1 signature changed.
- [ ] **No new API key for the agent.** Posting prepare runs via `run_agent_task("applier", ...)` (claude CLI); the `applier` agent is the one registered in Phase 1 — no second agent, no key.
- [ ] **No manual migration.** `PostingApplication` auto-creates via `init_db`'s `create_all`; conftest imports `models` first (test_posting_model passes on the isolated DB).
- [ ] **No real network/browser in tests.** Board fetches stub `postings.http_get_json`; form fill stubs `outlook.BrowserFiller.fill`; sends stub `outlook.send_mail`; the agent prepare is stubbed via `ap.prepare_posting`.

## Final full-suite verification

- [ ] Run the entire suite and confirm green (no regressions in Phase 0/1 or existing tests):
  `cd /Users/clawd/borina-mesh/apps/api && .venv/bin/python -m pytest -q`
  Expected: all tests pass (Phase 2 adds ~27 tests across `test_posting_model`, `test_browser_filler`, `test_postings_discover`, `test_postings_pipeline`, `test_postings_telegram`, `test_apply_command_postings`; the Phase 0/1 suite is unchanged). If any pre-existing or Phase-1 test fails, it must fail identically on the Phase-1 tip before this branch — otherwise fix the regression before declaring done.
