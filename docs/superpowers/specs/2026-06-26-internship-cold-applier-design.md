# Internship Cold-Applier — Design (all phases)

**Date:** 2026-06-26
**Status:** Approved (design), pending per-phase implementation plans
**Owner:** Bo

## Problem

Bo wants to apply to AI-focused internships at scale without the repetitive
discovery, drafting, and form-filling. The Borina Mesh already runs a fleet of
propose-only agents; this adds one (`applier`) that finds the right companies,
contacts, and postings, prepares a tailored application for each, and queues it
for Bo's one-tap approval — never sending or submitting anything on its own.

This document is the **full multi-phase vision** so it reads end-to-end. Each
phase is still built and planned separately (own implementation plan), in order,
so nothing is built on an unvalidated foundation.

## Goals

- A propose-only `applier` fleet agent running a discover → prepare → stage →
  approve → send/submit pipeline.
- Two role tracks: **AI-focused SWE** and **AI-focused finance** internships
  (Bo is a business major).
- Startup-leaning targets, near **Toronto** or **remote** (incl. remote-from-SF).
- Draft from Bo's Obsidian profile note + attach a resume PDF.
- Send from Bo's **UofT (Microsoft 365)** mailbox via Microsoft Graph, with a
  **browser-automation fallback** if the tenant blocks Graph consent.
- Triggers: on-demand (`apply:` Telegram command) + a weekly proactive batch.
- Grow from cold email → job-board applications → a tracked outreach pipeline
  with reply detection and follow-ups.

## Non-goals

- No autonomous sending or form submission. Every send/submit is gated on an
  explicit user approval (mirrors the calendar approve-to-write invariant).
- No credential storage in the repo; no scraping of authenticated sites beyond
  Bo's own logged-in sessions (browser fallback / form fill).
- Not a general CRM — the tracking layer (Phase 3) covers only Bo's own outreach.

## Phase roadmap

| Phase | Delivers | Depends on |
|------|----------|------------|
| **0. Validate send** | Azure app + OAuth consent on UofT account + one test email via Graph. Decides the primary send transport. | — |
| **1. Cold email** | `applier` agent + discover → enrich → draft → stage → approve → **send** (Graph or browser). On-demand + weekly. | Phase 0 |
| **2. Postings + forms** | Discover job-board postings; prepare cover letter/answers; **auto-fill** application forms (browser), human-submit gate; email-postings reuse Phase 1 send. | Phase 1 |
| **3. Track + follow up** | Reply detection (read mailbox), status pipeline, follow-up drafts, an **Outreach** frontend tab + weekly digest. | Phase 1 (2 optional) |

## Shared architecture

Approach A: a dedicated `applier` fleet agent plus single-purpose pipeline units,
reusing the mesh's existing patterns — fleet roster, integration wrappers
(`IntegrationResult`/`not_connected`), approval `Card`s + callback routing, OAuth
routes (mirroring the Calendar OAuth), the scheduler, and Telegram command
routing (like `build:` / `goal:`).

```
trigger (apply: command | weekly cron)
  → discover   targets (companies/contacts in P1; postings in P2)
  → prepare    tailored email / cover letter / answers (applier agent)
  → stage      OutreachItem / PostingApplication (status=proposed)   [NEVER sends]
  → approve    Card → Bo taps Send / Submit / Skip
  → act        send_mail / fill+submit, ONLY on user_initiated approval
  → mark       sent | submitted | failed | skipped
```

**Invariant across all phases:** the only outbound action paths
(`outlook.send_mail`, form-submit) are gated on `user_initiated=True` and
reachable only from Bo's approval tap. The pipeline/agent/enrichment are
text/data-only.

Common components:

- **`agents/applier.py`** — the preparing persona (registered in `fleet_roster`
  seed + `AGENT_REGISTRY`; routable/schedulable). Does the *prepare* step.
- **`dispatch/apply.py`** — pipeline orchestrator + batch/card builder. Text-only.
- **Approval `Card`s** — reuse `dispatch/cards.py`; new callback verbs in the
  Telegram router (`apply:send:{id}`, `apply:skip:{id}`, `apply:submit:{id}`).
- **Staging tables** — `OutreachItem` (P1) and `PostingApplication` (P2); both
  created by `init_db()`'s `create_all` (new tables, no manual migration).
- **Profile + resume** — `04-resources/applications/profile.md` (brag-doc the
  agent drafts from) + `resume.pdf` (attached/uploaded). If the resume is
  missing, the pipeline still prepares but flags "no resume" on the card.

---

## Phase 0 — Validate Microsoft send

The main feasibility risk: UofT controls the Microsoft tenant and may block
user-consent for a third-party app's delegated `Mail.Send` scope (Microsoft 365
also has basic-auth SMTP disabled, so OAuth + Graph is the only API route).

**Deliverable:** register a minimal Azure app, run OAuth consent with Bo's UofT
account, send ONE test email via Graph `/me/sendMail`. Outcome sets the primary
send transport:

- **Graph consent works** → Graph is primary (robust, works from the weekly cron).
- **UofT blocks it** → fall back to (a) a personal Outlook/Microsoft account as
  sender, or (b) the **browser-automation** transport as primary (good on-demand;
  brittle for the unattended cron — session/MFA expiry).

Everything downstream is transport-agnostic via a `Sender` interface, so Phase 0
only decides which implementation is wired in.

**Components:** `integrations/microsoft_oauth.py` (auth-code flow, scopes
`offline_access Mail.Send User.Read`, refresh token at
`~/.borina/ms_oauth_token.json`) + `routes/outlook.py`
(`/outlook/oauth/start`, `/outlook/oauth/callback`) — mirroring
`integrations/google_oauth.py` and the calendar OAuth routes.

---

## Phase 1 — Cold email pipeline

The v1. Discover AI startups, enrich contacts, draft a tailored cold email per
target, stage it, and send only on Bo's approval.

### Data model

```python
class OutreachItem(SQLModel, table=True):
    id: Optional[int] = primary key
    track: str                 # "swe" | "finance"
    company: str
    company_domain: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: str
    subject: str
    body: str
    status: str = "proposed"   # proposed | sent | skipped | failed
    dedup_key: str = indexed   # normalized contact_email (+ domain)
    send_via: Optional[str] = None   # "graph" | "browser"
    error: Optional[str] = None
    created_at: datetime = indexed, default utcnow
    sent_at: Optional[datetime] = None
```

### Pipeline

- **Discover** — web research assembles candidate AI startups per track, filtered
  to Toronto-area or remote-friendly. Output `[{company, domain, why_fit, track}]`.
- **Enrich** — `integrations/contacts.py` (Hunter or Apollo; key from env;
  `IntegrationResult` pattern) resolves the best hiring contact + a verified email
  (recruiter / founder / `careers@`) + confidence. Candidates with no confident
  email are dropped (logged, not silent).
- **Draft** — the `applier` agent writes a short, specific cold email per target:
  references the company's actual AI work, ties it to Bo's profile, names the
  track, asks about internships. Per-track tone (SWE vs finance).
- **Stage** — one `OutreachItem(status="proposed")` per draft. Nothing is sent.
- **Approve** — `Card{headline: company + track, lines: [contact, subject, body
  preview], actions: [Send, Skip]}`. `apply:send:{id}` → send; `apply:skip:{id}`
  → skipped.
- **Send** — on the Send tap only, `integrations/outlook.send_mail(to, subject,
  body, attachments=[resume], user_initiated=True)` via the wired `Sender`
  (Graph primary, Browser fallback). Success → `sent` + `send_via` + `sent_at`;
  failure → `failed` + `error` (kept retryable, like a disconnected calendar item).

### Triggers & volume

- **On-demand:** `apply: <optional criteria>` (e.g. `apply: AI fintech, remote`).
  Bare `apply:` uses defaults (both tracks, Toronto / remote-SF). Forbidden-gate
  exempt like `build:`, but still allow-listed and propose-only.
- **Weekly cron:** registered in `scheduler.py` (default **Mon 9:00 ET**).
- **Caps:** ~6–8 targets/batch (mixed tracks); a **daily send cap** (≤10) at send
  time for deliverability; **dedup** so a company/contact is never emailed twice
  (vs `OutreachItem` history + optional `04-resources/applications/blocklist.md`).

### Send transports

`integrations/outlook.send_mail(..., user_initiated=False)` refuses unless
`user_initiated`. Two backends behind one interface:

- **GraphSender** — Microsoft Graph `POST /me/sendMail` (primary).
- **BrowserSender** — Playwright driving Bo's logged-in Outlook web (fallback;
  attaches resume via compose UI). Best on-demand; brittle for the cron.

---

## Phase 2 — Job-board postings + application forms

The "Both, email-first" path Bo chose. Adds posting discovery and application
preparation/submission for roles that live on boards rather than cold contacts.

### Sources

LinkedIn Jobs, Wellfound (AngelList), Y Combinator "Work at a Startup", Indeed,
company career pages, and UofT's **CLNx** student board. Most lack open APIs, so
discovery is web-fetch/search + light parsing; the actual application is via the
posting's apply link.

### Data model

```python
class PostingApplication(SQLModel, table=True):
    id: Optional[int] = primary key
    track: str                 # "swe" | "finance"
    source: str                # "linkedin" | "wellfound" | "yc" | "career_page" | "clnx" | ...
    company: str
    role_title: str
    location: Optional[str] = None
    posting_url: str = indexed
    submit_method: str         # "email" | "form" | "external"
    ats: Optional[str] = None  # "greenhouse" | "lever" | "workday" | None
    cover_letter: Optional[str] = None
    answers_json: str = "{}"   # common-question answers
    status: str = "proposed"   # proposed | prepared | submitted | skipped | failed
    dedup_key: str = indexed   # company + role_title
    error: Optional[str] = None
    created_at: datetime = indexed
    submitted_at: Optional[datetime] = None
```

### Pipeline

- **Discover** — query the boards for AI SWE/finance internships (Toronto/remote),
  filter by track + recency + AI-relevance. Stage `PostingApplication(proposed)`.
- **Prepare** — the `applier` agent tailors a **cover letter** + a **resume-fit
  summary** + **answers to common application questions** (why this company, etc.)
  from `profile.md` + resume. Status → `prepared`.
- **Approve** — a Card per posting (company, role, location, apply method, cover
  preview, [Submit / Skip / Open]).
- **Submit** — on approval only:
  - `submit_method=email` → reuse Phase 1 `outlook.send_mail` (approval-gated).
  - `submit_method=form` → **BrowserFiller** (Playwright) fills name/email/resume
    upload/cover letter/answers in Bo's logged-in browser, then **stops before the
    final submit** and surfaces a "ready to submit — review & submit" card; **Bo
    clicks submit himself** (human-submit gate). Optionally, with an explicit
    "Auto-submit" approval, the agent clicks submit.
  - `submit_method=external` (Workday/heavy ATS, captchas, SSO) → the agent
    prepares the materials and hands Bo a deep link + the prepared text to paste;
    no auto-fill attempted (honest about brittleness).

### Honest constraints

Form auto-fill is per-site brittle. **Greenhouse/Lever** have semi-standard forms
(most automatable); **Workday** and custom SSO/captcha flows are not — those route
to `external` (prepare + hand off). The agent never solves captchas or logs into
third-party accounts on Bo's behalf. Default posture is **best-effort fill,
human submit**.

### Triggers

Folded into the same `apply:` command (covers both contacts and postings) and the
weekly cron; a batch can mix cold-email targets and postings, each as its own card.

---

## Phase 3 — Tracking, replies, follow-ups, Outreach tab

Turns one-shot sends into a tracked pipeline.

- **Status pipeline** — every `OutreachItem` / `PostingApplication` already carries
  status + timestamps. Phase 3 adds derived stages: `proposed → sent/submitted →
  replied → interview → offer/rejected`.
- **Reply detection** — read Bo's mailbox (Graph `Mail.Read` scope, or Gmail if on
  that fallback) and match incoming mail to outreach by recipient/thread; advance
  status (`replied`) and flag interview/rejection language for Bo's confirmation
  (never auto-classified as final without a glance). New consent scope (additive
  to Phase 0's app).
- **Follow-ups** — if no reply after **N days** (default 7), the agent drafts a
  short follow-up; staged as an approval card and sent via the Phase 1 path. Caps:
  at most one follow-up per contact; respect the daily send cap; honor the
  blocklist + any "do not follow up" flag.
- **Outreach frontend tab** — a new `/outreach` tab in `apps/web` (like `/daily`,
  `/finance`): the pipeline board (counts by stage), per-company rows with status
  + next action, and the week's sends/replies. Read-only over the API; actions
  still happen via Telegram approval.
- **Weekly digest** — an eod/weekly card: "N sent, M replies, K awaiting
  follow-up," with the follow-up batch proposed for approval.

---

## Cross-cutting safety (all phases)

- **Propose-only.** The sole outbound paths (`send_mail`, form submit) require
  `user_initiated=True` and are reachable only from Bo's approval tap. Reply
  detection is read-only and never auto-replies.
- **Fail-closed externals.** Enrichment, OAuth, board fetches, and the browser
  transports return `not_connected`/error on any problem → no send/submit. A
  failed send/submit is retryable, never silently lost.
- **Allow-list.** `apply:` + all callbacks ride the existing fail-closed Telegram
  allow-list.
- **No secrets in repo.** API keys via env; OAuth refresh tokens under `~/.borina`;
  browser transports use Bo's own logged-in sessions, no stored credentials.
- **Dedup + caps.** No company/contact emailed twice; no posting applied to twice;
  per-batch and daily caps; one follow-up max per contact.
- **No silent caps.** Whenever discovery/enrichment/board-fetch drops candidates
  (no email, over cap, deduped, brittle ATS), the batch summary says how many were
  dropped and why.
- **Human-submit default** for web forms; auto-submit only on an explicit extra
  approval.

## Cross-cutting testing (hermetic — matches repo's pytest + conftest style)

- **Staging never sends:** P1/P2 pipelines stage items with no `send_mail`/submit
  call during preparation (the core invariant).
- **Approval gating:** `apply:send`/`apply:submit` calls the outbound path with
  `user_initiated=True` exactly once and flips status; `apply:skip` acts on
  nothing.
- **Transports refuse without `user_initiated`;** Graph, Browser, and form-fill
  backends are stubbed (no real network/browser in tests).
- **Dedup + caps:** repeats and over-cap items are dropped/deferred and reported.
- **Lifecycle:** `proposed → sent/submitted` on success; `→ failed` (retryable) on
  error; `→ skipped` on skip; P3 `→ replied` on a matched inbound stub.
- **Card render + callback routing:** correct verbs; router dispatches to the
  right item.
- **P3 reply matcher:** a stubbed inbound email matches the right outreach;
  follow-up respects the N-day window + one-per-contact cap.

## Setup dependencies (Bo provides; not code)

- A **Hunter** (or **Apollo**) API key → `HUNTER_API_KEY` / `APOLLO_API_KEY`. (P1)
- An **Azure app registration** (client id/secret + redirect URI
  `http://localhost:8000/outlook/oauth/callback`); consent run once via
  `/outlook/oauth/start`. `Mail.Send` for P1; add `Mail.Read` for P3. (P0/P3)
- For the **browser** transports: logged-in Outlook + board sessions on the Mini. (P1/P2)
- `profile.md` + `resume.pdf` under `04-resources/applications/`. (P1)

## Open questions / defaults (tunable)

- Enrichment provider: default **Hunter** unless Bo has Apollo (isolated behind
  `contacts.find_contact`).
- Weekly cron **Mon 9:00 ET**, batch **6–8**, daily send cap **10**, follow-up
  window **7 days** — defaults.
- Phase 2 board priority: start with **Wellfound + YC + company career pages**
  (most startup/AI-dense, friendlier to fetch) before LinkedIn/Workday.
- Auto-submit for forms is opt-in per approval; default human-submit.

## Affected files (by phase)

- **P0/P1:** `apps/api/models.py` (`OutreachItem`); `agents/applier.py` +
  `fleet_roster` + `AGENT_REGISTRY`; `dispatch/apply.py`;
  `integrations/contacts.py`; `integrations/outlook.py`;
  `integrations/microsoft_oauth.py` + `routes/outlook.py`;
  `routes/telegram.py` (`apply:` + send/skip callbacks); `scheduler.py` (weekly
  cron); `apps/api/tests/`.
- **P2:** `models.py` (`PostingApplication`); board discovery + form-fill in
  `dispatch/apply.py` (or a `dispatch/postings.py`); `integrations/outlook.py`
  (BrowserFiller); `routes/telegram.py` (`apply:submit`); tests.
- **P3:** mailbox read in `integrations/outlook.py` (Graph `Mail.Read`); reply
  matcher + follow-up in `dispatch/apply.py`; `routes/outreach.py` + an
  `/outreach` tab in `apps/web`; weekly digest in `scheduler.py`/`daily_operator`;
  tests.

## Implementation phasing

Build in order — **0 → 1 → 2 → 3** — each as its own implementation plan and
branch, shipped and verified before the next. Phase 0 gates everything (it decides
the send transport); Phase 1 is the usable MVP; Phases 2–3 extend reach and add
tracking. This keeps every step shippable and avoids building on an unvalidated
foundation.
