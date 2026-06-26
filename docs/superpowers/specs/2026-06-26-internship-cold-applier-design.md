# Internship Cold-Applier — Design

**Date:** 2026-06-26
**Status:** Approved (design), pending implementation plan
**Owner:** Bo

## Problem

Bo wants to cold-apply to AI-focused internships at scale without doing the
repetitive discovery + drafting by hand. The Borina Mesh already runs a fleet of
propose-only agents; this adds one that finds the right companies and contacts,
drafts a tailored cold email for each, and queues it for Bo's one-tap approval to
send — never sending anything on its own.

## Goals

- A new propose-only fleet agent (`applier`) that runs a discover → enrich →
  draft → stage → approve → send pipeline.
- Two role tracks: **AI-focused SWE** internships and **AI-focused finance**
  internships (Bo is a business major).
- Startup-leaning targets, located near **Toronto** or **remote** (incl.
  remote-from-SF).
- Draft from Bo's Obsidian profile note + attach a resume PDF.
- Send from Bo's **UofT (Microsoft 365)** mailbox via Microsoft Graph, with a
  **browser-automation fallback** if the tenant blocks Graph consent.
- Triggers: on-demand (`apply:` Telegram command) + a weekly proactive batch.

## Non-goals

- **v1 is cold email only.** Job-board postings / web application-form filling is
  a deferred **v2** phase (own spec/plan).
- No autonomous sending. The only send path is gated on an explicit user approval
  (mirrors the calendar approve-to-write invariant).
- No credential storage in the repo; no scraping of authenticated sites beyond
  Bo's own logged-in Outlook session (browser fallback).

## Phase 0 — validate Microsoft send FIRST (do before building the pipeline)

The main feasibility risk is that UofT controls the Microsoft tenant and may block
user-consent for a third-party app's delegated `Mail.Send` scope (and Microsoft
365 has basic-auth SMTP disabled, so OAuth + Graph is the only API route).

**Phase 0 deliverable:** register a minimal Azure app, run the OAuth consent with
Bo's UofT account, and send ONE test email via Graph `/me/sendMail`. Outcome
decides the primary send transport:

- **Graph consent works** → Graph is primary (robust, works from the weekly cron).
- **UofT blocks it** → fall back to either (a) a personal Outlook/Microsoft
  account as sender, or (b) the browser-automation transport as primary (good
  on-demand; brittle for the unattended cron — see Send).

Everything downstream is transport-agnostic, so Phase 0 only swaps which `Sender`
implementation is wired in.

## Architecture

Approach A: a dedicated `applier` fleet agent plus a pipeline of single-purpose
units, reusing the mesh's existing patterns (fleet roster, integration wrappers,
approval cards, OAuth routes, scheduler, Telegram command routing).

```
trigger (apply: command | weekly cron)
  → discover   AI startups (web research; Toronto / remote), per track
  → enrich     best contact + verified email per company (Hunter/Apollo)
  → draft      tailored cold email from profile.md + resume.pdf (applier agent)
  → stage      OutreachItem(status=proposed)  [NEVER sends]
  → approve    Card (contact, subject, body) → Bo taps Send / Skip
  → send       Sender.send(item, user_initiated=True)  [Graph | browser]
  → mark       sent | failed
```

### Components (one responsibility each)

1. **`agents/applier.py`** — the drafting persona (registered in `fleet_roster`
   seed + `AGENT_REGISTRY`; routable/schedulable like other fleet agents). Its
   job is the *draft* step: turn (company, contact, track, profile, resume-summary)
   into a tailored subject + body.
2. **`dispatch/apply.py`** (pipeline orchestrator) — runs discover → enrich →
   draft → stage for a batch; returns the staged `OutreachItem`s and sends the
   approval Cards. Text-only; never sends mail.
3. **`integrations/contacts.py`** — enrichment wrapper (Hunter or Apollo) using
   the `IntegrationResult` / `not_connected` pattern; key from env
   (`HUNTER_API_KEY` / `APOLLO_API_KEY`). `find_contact(company, domain) ->
   IntegrationResult` (best contact + verified email + confidence).
4. **`integrations/outlook.py`** — `send_mail(to, subject, body, attachments, *,
   user_initiated=False) -> IntegrationResult`. Refuses unless `user_initiated`
   (same hard gate as calendar writes). Two backends behind one interface:
   - **GraphSender** — Microsoft Graph `POST /me/sendMail` (primary).
   - **BrowserSender** — Playwright driving Bo's logged-in Outlook web (fallback).
5. **`integrations/microsoft_oauth.py`** + `routes/outlook.py`
   (`/outlook/oauth/start`, `/outlook/oauth/callback`) — auth-code flow against
   the Microsoft identity platform, scopes `offline_access Mail.Send User.Read`,
   refresh-token persisted at `~/.borina/ms_oauth_token.json`. Mirrors the
   existing `integrations/google_oauth.py` + calendar OAuth routes.
6. **`OutreachItem`** (new SQLModel table) — the staging row (see Data model).
7. **Approval Card + callbacks** — reuse `dispatch/cards.py` (`Card`, `Action`,
   `send_card`); new callback verbs `apply:send:{id}` / `apply:skip:{id}` in the
   Telegram callback router (alongside the existing `op:` / planner verbs).
8. **Triggers** — `apply:` command in `routes/telegram.process_update` (like
   `build:` / `goal:`), and a weekly cron registered in `scheduler.py`.

## Data model

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
    send_via: Optional[str] = None   # "graph" | "browser" (set on send)
    error: Optional[str] = None
    created_at: datetime = indexed, default utcnow
    sent_at: Optional[datetime] = None
```

Created by `init_db()`'s `create_all` (new table — no manual migration).

## Profile + resume source

- `04-resources/applications/profile.md` — Bo's brag-doc (skills, AI projects,
  links, what he's looking for). The draft step reads it for tailoring.
- `04-resources/applications/resume.pdf` — attached to each email (Graph
  attachment; for the browser fallback, attached via the compose UI from this
  path). If the resume is missing, the pipeline still drafts but flags
  "no resume attached" on the card.

## Discover + enrich

- **Discover:** the pipeline uses web research (the mesh's existing web-search
  capability) to assemble candidate AI startups per track, filtered to
  Toronto-area or remote-friendly. Output: `[{company, domain, why_fit, track}]`.
- **Enrich:** for each candidate, `contacts.find_contact` resolves the best
  hiring contact + a verified email (recruiter / founder / `careers@`). Drop
  candidates with no confident email (logged, not silently — see "no silent
  caps"). Bo reviews every survivor on a card regardless.

## Draft + approve + send

- **Draft:** the `applier` agent writes a short, specific cold email per target —
  references the company's actual AI work, ties it to Bo's profile, names the
  track, asks about internships. Per-track tone (SWE vs finance).
- **Stage:** one `OutreachItem(status="proposed")` per draft. Nothing is sent.
- **Approve:** a `Card{headline: company + track, lines: [contact, subject, body
  preview], actions: [Send, Skip]}`. `apply:send:{id}` → send; `apply:skip:{id}`
  → mark skipped. (Optionally `apply:sendall:{batch}` to send a whole approved
  batch — but each still only after Bo's tap.)
- **Send:** on the Send tap only, `outlook.send_mail(..., user_initiated=True)`
  via the wired `Sender`. On success → `status=sent`, `send_via`, `sent_at`. On
  failure → `status=failed`, `error`, surfaced back to Bo (kept retryable, like
  the calendar item that stays `proposed` when disconnected).

## Triggers & volume

- **On-demand:** `apply: <optional criteria>` (e.g. `apply: AI fintech, remote`).
  Bare `apply:` uses defaults (both tracks, Toronto / remote-SF). Runs one batch,
  sends the cards. Forbidden-gate exempt like `build:` (it's an outreach command,
  not a destructive action) — but still allow-listed and propose-only.
- **Weekly cron:** registered in `scheduler.py` (default **Mon 9:00 ET**), sources
  a fresh batch and sends approval cards.
- **Volume caps:** ~6–8 targets per batch (mixed tracks); a **daily send cap**
  (≤10) enforced at send time for deliverability; **dedup** so a company/contact
  is never emailed twice (checked against `OutreachItem` history + an optional
  `04-resources/applications/blocklist.md`).

## Safety

- **Propose-only.** The sole send path is `outlook.send_mail(user_initiated=True)`,
  reachable only from Bo's approval tap. The pipeline, agent, and enrichment are
  text/data-only.
- **Fail-closed externals.** Enrichment and OAuth return `not_connected` on any
  problem → no contact, no send. A failed send keeps the item retryable, never
  silently lost.
- **Allow-list.** `apply:` and the callbacks ride the existing fail-closed
  Telegram allow-list.
- **No secrets in repo.** API keys via env; OAuth refresh token under `~/.borina`;
  the browser fallback uses Bo's own logged-in session, no stored credentials.
- **No silent caps.** When discovery/enrichment drops candidates (no email, over
  the cap, deduped), the batch summary says how many were dropped and why.

## Testing (hermetic — matches the repo's pytest + conftest style)

- **Pipeline:** discover/enrich stubbed → drafts stage `OutreachItem(proposed)`;
  no `send_mail` is called during staging (the core invariant).
- **Dedup:** a contact already in `OutreachItem` (or blocklist) is dropped.
- **Approval gating:** `apply:send:{id}` calls `send_mail(user_initiated=True)`
  exactly once and flips status to `sent`; `apply:skip:{id}` sends nothing.
- **Volume caps:** batch size + daily send cap enforced; overflow reported.
- **Send transports:** `outlook.send_mail` refuses without `user_initiated`;
  Graph + browser backends both stubbed (no real network/browser in tests).
- **Lifecycle:** `proposed → sent` on success, `proposed → failed` (retryable) on
  send error; `skipped` on skip.
- **Card render + callback routing:** the card carries the right verbs; the
  router dispatches send/skip to the right item.

## Setup dependencies (Bo provides; not code)

- A **Hunter** (or **Apollo**) API key → `HUNTER_API_KEY` / `APOLLO_API_KEY`.
- An **Azure app registration** for the Graph route (client id/secret + redirect
  URI `http://localhost:8000/outlook/oauth/callback`); consent run once via
  `/outlook/oauth/start`. (Phase 0.)
- For the **browser fallback**: a logged-in Outlook web session on the Mini.
- `profile.md` + `resume.pdf` under `04-resources/applications/`.

## Open questions / defaults (tunable)

- Enrichment provider: default **Hunter** (domain → email + confidence) unless Bo
  has Apollo; the wrapper isolates this behind `contacts.find_contact`.
- Weekly cron time **Mon 9:00 ET**, batch **6–8**, daily send cap **10** — defaults.
- `apply:sendall` batch-approve is optional; ship single-tap send first.

## Affected files (anticipated)

- `apps/api/models.py` — add `OutreachItem`.
- `apps/api/agents/applier.py` — new drafting agent; `fleet_roster` seed +
  `AGENT_REGISTRY` entry; intent routing.
- `apps/api/dispatch/apply.py` — new pipeline orchestrator + batch/card builder.
- `apps/api/integrations/contacts.py` — new enrichment wrapper.
- `apps/api/integrations/outlook.py` — new `send_mail` + Graph/Browser senders.
- `apps/api/integrations/microsoft_oauth.py` + `apps/api/routes/outlook.py` — new
  OAuth (mirrors google_oauth + calendar routes).
- `apps/api/routes/telegram.py` — `apply:` command + `apply:send`/`apply:skip`
  callbacks.
- `apps/api/scheduler.py` — register the weekly applier cron.
- `apps/api/tests/` — new tests per the Testing section.
- (Frontend, optional later: an Outreach tab; not in v1.)

## Phasing

- **v1 (this spec):** cold-email pipeline end-to-end (Phase 0 send validation →
  discover/enrich/draft/stage/approve/send, on-demand + weekly).
- **v2 (later, own spec):** job-board postings + web application-form prep/filling
  (browser automation), the "Both, email-first" path Bo chose.
