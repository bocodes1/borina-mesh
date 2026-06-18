# Borina Mesh — Foundation Slice (Lean Fleet + Clean Remote)

**Date:** 2026-06-18
**Status:** Approved design, ready for implementation plan
**Slice:** 1 of N (L0 + L1) on the road to an autonomous agentic OS

---

## 1. Context

Borina Mesh is a self-hosted multi-agent OS (FastAPI `apps/api` :8000 + Next.js
`apps/web` :3000) running 24/7 on a Mac Mini, served via the Claude Max
subscription through the `claude` CLI (no API key). Agents are reachable over
Telegram and a web cockpit.

The owner wants to evolve it from "a chatbot you poke" into **a staff you
delegate to**: it takes long-horizon goals and grinds with milestone check-ins,
runs the day proactively (calendar included), and self-manages its own fleet.

That full vision is a multi-layer build. It is decomposed into slices, each with
its own spec → plan → implementation cycle:

- **L0 — Lean the fleet:** retire dead agents, park unused ones.
- **L1 — Telegram as a clean remote:** fix sloppy output, add a real control surface.
- **L2 — Daily operator:** proactive routine + calendar writes (deferred).
- **L3 — Goal long-runner:** durable, milestone-checked, steerable goals (deferred).
- **L4 — Self-management:** the OS prioritizes its own queue and fleet (deferred).

**This spec covers Slice 1 = L0 + L1 only.** Foundation first: every autonomous
behavior built later inherits the quality of a lean fleet and a clean control
surface, so these are built before anything more ambitious.

### Grounding (real data from recon, 2026-06-18)

Usage from the live DB (`apps/api/borina.db`, 2,324 jobs total):

| Agent | Jobs | Last run | Verdict |
|---|---|---|---|
| `trader` | 1,694 (73%) | active (<2h) | **keep — core** |
| `inbox-triage` | 430 | active (<2h) | **keep — core** |
| `adset-optimizer` | 37 | today (cron) | **park** |
| `ecommerce-scout` | 36 | today (cron) | **park** |
| `ceo` | 48 | Jun 15 (rare) | **keep — infra (powers missions)** |
| `researcher` | 40 | Jun 15 (rare) | **keep — infra (intent fallback)** |
| `polymarket-intel` | 34 | Jun 15 (rare) | **retire (overlaps `trader`)** |
| `builder` | 2 | Jun 14 | keep (not in this slice's roster work) |
| `qa_director` | 2 / **0 successful** | Jun 2 (dead) | **retire** |
| `finance` (agent shell) | 0 / never | never | **retire shell** |
| `planner` (agent shell) | 0 / never | never | **retire shell** |
| legacy `polymarket` dupe | 1 | Jun 14 | **retire** |
| `curator` | disabled | — | **retire** |

Key facts the design depends on:
- `trader` + `inbox-triage` are **91% of all activity**. The rest is a long tail.
- `finance` and `planner` are registered fleet agents that have **never been
  dispatched** — their daily-brief / day-plan *logic* runs via cron
  (`planner.generate_plan_with_agent`, `planner.py:325`) and the web tab, **not**
  through the agent dispatch path. Retiring the agent *shells* does not touch
  those features.
- `qa_director` (the "judgment/QA gatekeeper") has **0 successful runs** — the
  quality layer is vestigial.
- `AgentConfig.schedule_cron` / `last_run_at` columns exist but are **dead code**
  (`models.py:54-59`); the `agentconfig` table has **0 rows**.
- Schedules are **hardcoded in Python** with an in-memory APScheduler jobstore
  (`scheduler.py:398`, wired `main.py:64-68`); nothing survives a restart and
  runtime `PUT /schedules` edits vanish.
- The Telegram inline-button **receiver** already exists
  (`routes/telegram.py:49`, `callback_query` handling). Only a button **sender**
  (`reply_markup` emitter) is missing.

---

## 2. Goals & non-goals

### Goals (this slice)
1. Reduce the fleet to **4 active agents** (`trader`, `inbox-triage`, `ceo`,
   `researcher`), with `adset-optimizer` and `ecommerce-scout` **parked**
   (dormant but reactivatable), everything else **retired**.
2. Make the fleet roster **data, not hardcode** — revive `AgentConfig` as the
   source of truth for agent state + schedule, surviving restarts.
3. Make Telegram replies **clean and predictable** — no escaping artifacts, no
   format roulette, no mid-word truncation, no eaten symbols.
4. Give the user a **discoverable control surface** — slash commands +
   inline buttons, including the ability to see and cancel running jobs.
5. Ship a small **structured-card message model** with one live consumer
   (`/jobs` cancel), establishing the channel that L2/L3 will reuse.
6. **Scope the forbidden gate** so it stops blocking read-only questions while
   staying fail-closed for real writes.

### Non-goals (deferred to later slices)
- Calendar write/move/delete, free/busy gap-finding, day-plan auto-commit (L2).
- Milestone check-ins, durable goal state, mid-flight steering (L3).
- Queue prioritization, automatic agent retire/spawn (L4).
- Full re-architecture of every agent's output contract (rejected in favor of
  the hybrid approach — new message types are structured; legacy free-text
  answers ride the patched formatter).
- Web UI changes beyond what naturally follows from the roster table (the web
  cockpit already reads agent/job data; no new tabs in this slice).

### Safety invariants (must not weaken)
- Telegram remains fail-closed: secret-token check + `TELEGRAM_ALLOWED_CHAT_IDS`
  allow-list.
- Dispatch and planner stay read-only / propose-only. No autonomous calendar or
  money writes are introduced in this slice.
- The forbidden gate is *scoped*, not *removed* — real action verbs in command
  position are still refused.

---

## 3. Design

Five components, labelled A–E.

### A. Fleet roster as data (`AgentConfig` revival) — L0 + substrate fix

**What:** Promote `AgentConfig` from dead columns to the authoritative fleet
roster and schedule store.

**Schema (extend `models.py` `AgentConfig`):**
- `agent_id: str` (pk / unique) — matches the registry id.
- `state: str` — one of `active | parked | retired`.
- `schedule_cron: str | null` — cron string; null = no proactive schedule.
- `last_run_at: datetime | null` — stamped by the scheduler/worker on each run.
- (keep any existing columns; add `state` if absent.)

**Semantics:**
- `active` — routable by intent, schedulable, listed in `/help` and `/fleet`.
- `parked` — **not** scheduled, **not** auto-routed, **hidden** from `/help`;
  still summonable by explicit name (`adset-optimizer: …`), which is how it gets
  reactivated on demand. This is exactly "deactivate the cron noise, keep the
  agent."
- `retired` — removed from the registry/routing entirely; no schedule, not
  summonable.

**Migration / seed:** a one-time idempotent seed populates `agentconfig` from the
current registry with the decided states:
- active: `trader`, `inbox-triage`, `ceo`, `researcher`
- parked: `adset-optimizer`, `ecommerce-scout`
- retired: `polymarket-intel`, `qa_director`, `finance`, `planner`, legacy
  `polymarket`, `curator`
- (`builder` left as-is; not part of this slice's roster surgery.)

**Scheduler change:** `scheduler.py` reads jobs from `AgentConfig` rows where
`state == active` and `schedule_cron is not null`, instead of the hardcoded list.
Result: schedules survive restart, and parked/retired agents produce no crons.
The chief-of-staff cron jobs (finance brief, daily brief, planner) keep running
as *system* jobs (they call generator functions directly, not agent dispatch),
so retiring the `finance`/`planner` agent shells does not stop them.

**Routing change:** `dispatch/intent.py` resolves only `active` (or
explicitly-named `parked`) agents; retired ids never match. The intent fallback
remains `researcher`.

**Edge cases:**
- An incoming `<parked-agent>: task` reactivates-on-demand for that one run but
  does not flip `state` (explicit `/fleet` reactivate does that).
- A registry agent with no `AgentConfig` row defaults to `active` on seed only;
  after seed, missing row = treat as retired (the table is authoritative).

### B. Reply formatting — kill sloppiness at the source

Touchpoints: `dispatch/telegram_format.py:85`, `dispatch/dispatcher.py`
(`format_answer_reply` / `format_dispatch_reply`), `dispatch/answer.py:129`
(`wants_pdf`).

1. **HTML, not MarkdownV2.** Switch outbound `parse_mode` to HTML. Render the
   agent's markdown answer to a Telegram-safe HTML subset (bold, italic, inline
   code, links; lists flattened to `• ` lines; headings → bold lines). Eliminates
   the `3\.2% \(Q1\)\.` backslash spatter and the literal `*#•>` leakage.
2. **Format by answer size, not keywords.** Delete the `wants_pdf` regex trigger
   that fires on the raw word "report." Decision:
   - **short** (≤ ~1500 chars / ≤ ~8 lines) → send the full clean answer.
   - **long** → send a tight TL;DR headline + key points, plus a link to the full
     `.md` artifact.
   - A `.md` artifact is **always** written (unchanged).
3. **PDF only on explicit ask.** PDF is generated only when the request contains
   an explicit intent (`/pdf`, or "as pdf" / "as a pdf"). It never auto-hijacks a
   normal answer.
4. **Clean truncation.** When trimming a long answer for chat, cut on a paragraph
   boundary and append `… full answer: <link>`. Never cut mid-word/mid-sentence.
   Only reference a PDF link if a PDF was actually produced.
5. **Narrow the emoji stripper.** Restrict it to leading/decorative emoji only;
   stop the broad unicode sweep that eats `→ ↑ ✓ ™` and similar meaningful glyphs.

### C. Discoverable control surface

Register commands via Telegram `setMyCommands` (on startup) so they autocomplete
in the client. Handlers live in `routes/telegram.py` / `dispatch`.

| Command | Behavior |
|---|---|
| `/help` | What Borina can do; the command list; documents the colon-syntax for power users (`trader:`, `mission:`). |
| `/jobs` | List running + recent jobs (agent, status, age). Each running job renders an inline **[Cancel]** button (see D). |
| `/fleet` | Show the roster + states (active / parked). Parked rows render a **[Reactivate]** button. |
| `/cancel <id>` | Abort a job by id (also reachable via the `/jobs` button). |

The colon-syntax (`trader: …`, `mission: …`, `remember:` / `recall:`, `build:`)
remains and is now documented in `/help`. `/cancel` and `/jobs` wire to the
existing `POST /jobs/{id}/cancel` route.

### D. Structured card model (the hybrid payoff)

**What:** a minimal structured message type plus a single renderer and a callback
dispatcher.

- `Card { headline: str, lines: list[str], actions: list[Action] }` where
  `Action { label: str, callback_data: str }`.
- One renderer: `Card → (html_text, inline_keyboard)` for Telegram (reusable by
  the web cockpit later). This adds the missing `reply_markup` **sender**.
- Extend the existing `callback_query` handler (`routes/telegram.py:49`) to parse
  `callback_data` and dispatch to a small registry of action handlers, preserving
  the allow-list / secret-token checks already enforced there.

**Slice-1 consumer:** the `/jobs` and `/cancel` flow. A `/jobs` listing emits a
Card per running job with a `[Cancel]` action whose `callback_data` carries the
job id; the callback handler calls the cancel route and edits the message to
reflect the new state. This proves the entire structured-card + button channel
end-to-end with one real use, so L2 (approval cards) and L3 (milestone
continue/steer/abort) reuse it without new plumbing.

`callback_data` convention: `"<verb>:<arg>"` (e.g. `cancel:1934`), echoing the
existing `approve:<id>` / `reject:<id>` convention so the handler stays uniform.

### E. Scope the forbidden gate

Touchpoint: `dispatch/intent.py` forbidden gate.

- Block only when an action verb is the **command intent** — message parses as an
  imperative to act (e.g. "buy X", "sell Y", "send Z", "delete W", "create a
  calendar event"). Use imperative/leading-verb position, not substring presence.
- Stop refusing read-only questions that merely contain a trigger word
  ("what happened when TSLA **dropped**", "summarize the **buy**-side flow").
- Keep fail-closed for genuine writes; no new write capability is granted. (An
  explicit override token is out of scope here since this slice adds no write
  paths — the fix is purely about not blocking legitimate read-only queries.)

---

## 4. Error handling

- **AgentConfig seed** is idempotent: re-running it must not duplicate rows or
  clobber a state the user changed via `/fleet`. Seed only fills missing rows /
  first-run defaults; explicit user state changes win.
- **HTML render** must never raise on malformed agent markdown — on any render
  error, fall back to escaped plain text (never send raw broken HTML, never crash
  the reply path).
- **Callback dispatch** validates `callback_data` shape and the chat allow-list
  before acting; unknown verbs are ignored with a benign "expired/unknown action"
  edit, never a stack trace.
- **`/cancel`** on an already-finished or unknown job replies with a clear,
  terse message; no error leakage.
- **Scheduler** tolerates a malformed `schedule_cron` in `AgentConfig` by logging
  and skipping that one job, not failing startup.

---

## 5. Testing strategy

Backend `pytest` (keep the ~283 suite green), frontend `vitest` (~65) unaffected
but re-run. New tests:

- **Roster/state gating:** a `parked` agent is not scheduled and not intent-routed;
  a `retired` agent never matches routing; an explicit `parked-agent:` call still
  dispatches; intent fallback remains `researcher`.
- **Scheduler from DB:** schedules are read from `AgentConfig`; a row added at
  runtime is honored; a malformed cron is skipped without crashing.
- **Seed idempotency:** running the seed twice yields the same rows; a
  user-changed state is preserved across a re-seed.
- **Formatter:** markdown → safe HTML (bold/links/lists/code); size threshold
  picks short-full vs long-TLDR+link; PDF only on explicit ask; truncation lands
  on a boundary and only links a PDF when one exists; `→ ↑ ✓ ™` survive.
- **Forbidden gate:** imperative action verbs are blocked; read-only questions
  containing trigger words pass; real write phrasing stays refused.
- **Card + callback:** `Card` renders expected HTML + inline keyboard;
  `cancel:<id>` callback invokes the cancel route and edits the message; unknown
  verb is handled benignly; allow-list still enforced on callbacks.

Hermetic via `apps/api/conftest.py` (existing pattern). No live Telegram or DB
side effects in tests.

---

## 6. Deployment

Standard launchd flow (no service restarts mid-build):
1. Commit to `feature/foundation-slice1`, open PR, merge to `origin/main` when
   approved.
2. `cd apps/web && npm run build`.
3. `launchctl kickstart -k gui/$(id -u)/com.borina.mesh-api` and `...mesh-web`.

The `AgentConfig` seed runs once on startup (idempotent). Because schedules move
into the DB, confirm post-deploy that the chief-of-staff crons still fire and
that parked agents produce no jobs.

---

## 7. Risks & open questions

- **Risk — schedule regression:** moving crons from Python to `AgentConfig` could
  silently drop a job. Mitigation: the seed must enumerate every currently-active
  cron; add a startup assertion/log of the loaded schedule for eyeball
  verification on first deploy.
- **Risk — HTML rendering edge cases:** agent output can contain `<`/`>`/`&` and
  code blocks. Mitigation: render through a small tested markdown→HTML function
  with strict escaping of non-tag content; the plain-text fallback covers misses.
- **Open (minor):** whether `/fleet` reactivation should require a confirmation
  tap. Default: no — it's reversible and low-risk. Revisit if it feels too easy.
- **Out of scope but noted:** the calendar layer is append-only (no patch/delete)
  and there is no free/busy gap-finding — both are L2 concerns and are documented
  here only so the L2 spec inherits the finding.

---

## 8. What this unlocks

After this slice: a 4-agent lean fleet whose roster + schedules live in the DB
and survive restarts; predictable, clean Telegram replies; a discoverable command
surface; and a working structured-card + inline-button channel. L2 (daily
operator) and L3 (goal long-runner) then build approval cards and milestone
check-ins directly on the card/callback channel shipped here, instead of inventing
new plumbing.
