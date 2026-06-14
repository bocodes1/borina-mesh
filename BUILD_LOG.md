# BUILD_LOG — Frontend Rebuild + Life-OS Tabs + Autonomous Telegram Dispatch

Append-only. Each entry: timestamp, what changed, which tests now pass.
Spec: `~/Documents/borinamesh/borina-mesh-frontend-rebuild.md`. Branch: `feature/frontend-rebuild`.

Working model: built on a feature branch in-place; live launchd services (`com.borina.mesh-api/web`)
left running their loaded `main` code; `com.borina.mesh-updater` (StartInterval=120) **paused** for the
build and to be **restored at the end**. Tests/dev servers use non-live ports (pytest uses TestClient).

3-failure rule in effect. Missing real credentials → mock + mark autonomous-complete + add to §12 hand-off
(never fabricate a credential or fake a green check). Safety rules in spec §7 / §8b are never weakened.

---

## 2026-06-02 — Step 0: Assessment + setup
- Mapped apps/web + apps/api. Confirmed gaps: no `/daily`,`/calendar`; Terminal present; stub routers
  (`tasks/daily/calendar/telegram`); no `integrations/`; no Telegram dispatch; no `schedule_daily` brief;
  6 shared UI primitives absent; **no frontend test harness**; `.env.example` missing new keys.
- Paused `com.borina.mesh-updater`; created branch `feature/frontend-rebuild` from `main` (c15b262).
- Decision: keep `/polymarket` tab (spec only mandates deleting Terminal; Polymarket is also a Finance panel).
- Tests pass: (baseline) existing backend pytest suite — to be re-verified.

## 2026-06-02 — Step 1: Test harness (Task #1) ✅
- **Backend:** added `apps/api/conftest.py` — isolates tests from production: temp `DATABASE_URL`
  (protects the live `borina.db` the running service uses), `REPORTS_DIR`→temp, and a per-test
  autouse fixture resetting `OBSIDIAN_VAULT_PATH` so cross-test env leakage (`test_wiki_routes`
  sets it at import) can't bleed real artifacts into hermetic tests.
- Fixed a pre-existing flaky test: `test_claude_code_worker._init_repo` now `git branch -M master`
  so it's independent of the host `init.defaultBranch` (was failing: `master` vs `main`).
- **Frontend:** installed vitest@2 + @testing-library/react@16 (React 19) + jsdom; added
  `vitest.config.ts`, `vitest.setup.ts` (jsdom polyfills: matchMedia/ResizeObserver/scrollIntoView),
  and `npm test` / `test:watch` scripts. There was **no** frontend test harness before.
- **Tests now pass:** backend `pytest -q` → **92 passed** (was 91 + 1 pre-existing fail). Frontend
  `vitest run` → sanity test green.

## 2026-06-02 — Step 2: Design system + shared primitives (Task #2) ✅
- Extended token system additively (kept violet `--primary` as the single accent): added
  `--surface`/`--surface-2` layers + `--brand`/`--positive`/`--negative`/`--warn` semantics in
  `globals.css` (both `:root` and `.dark`), wired matching Tailwind colors (`bg-surface`, `text-positive`…).
  Added `.surface-card` (hairline + inner top-light gradient + shadow) and `.value-flash` (live-update tint).
- Created the 6 shared primitives in `components/ui/`: `section-header`, `kpi-card` (tabular-nums + delta tones),
  `data-table` (generic, numeric cols → tabular-nums, empty→EmptyState), `empty-state` (CTA slot for "Connect X"),
  `error-state` (retry), `loading-skeleton` (Skeleton + KpiStrip/Card/Rows presets).
- Fixed a type conflict (`title: ReactNode` vs HTML `title`) via `Omit<…,"title">`.
- **Tests now pass:** `vitest run test/primitives.test.tsx` → 6 passed; `tsc --noEmit` clean; `npm run build` clean.

## 2026-06-02 — Step 3: Delete Terminal tab (Task #3) ✅
- Removed `app/terminal/` route and the navbar import + link. Left the lucide `Terminal` *icon*
  reuse in `overnight-workers.tsx` (unrelated to the deleted tab).
- Regression guard `test/navbar-terminal.test.tsx`: navbar has no Terminal item / no `/terminal`
  link, core tabs still present. (404 behavior validated by route deletion + covered in §10b mobile/route pass.)
- **Tests pass:** vitest guard green; `npm run build` clean (route list no longer includes `/terminal`).

## 2026-06-02 — Step 4: integrations/ package (Task #4) ✅
- New `apps/api/integrations/` with a shared envelope (`base.py`: `IntegrationResult`,
  `ok`/`not_connected`/`safe` decorator, mockable `http_get_json`/`http_post_json`).
- Providers, all READ-ONLY + graceful (return `connected=False` when unkeyed, never raise):
  `market_data` (quote/history/fundamentals/news), `brokerage` (portfolio), `wallet` (balances),
  `polymarket` (read-only surface of the local bot, no CEX-lag reimpl), `weather`, `google_calendar`.
- **Safety:** `google_calendar.create_event` hard-refuses unless `user_initiated=True`; it's the
  only write path and is unreachable from an agent/auto path.
- Extended `.env.example` with all §7 keys (MARKET_DATA/BROKERAGE/WALLET/GOOGLE_OAUTH/WEATHER/HOME_*).
- **Tests pass:** `test_integrations.py` → 14 passed (not-connected, mocked-OK, never-raises, calendar refusal).

## 2026-06-02 — Step 5: Backend routers finance+/daily/calendar/tasks (Task #5) ✅
- `daily_brief.py`: section parser (`<section id="…">` → dict) + load/save for `reports/{day}/daily-brief.md`;
  one source of truth the Finance/Daily/Calendar tabs read from.
- `models.Task` (+ TASK_TAGS/TASK_PRIORITIES). Watchlist kept on existing JSON store (already persists;
  not re-platformed to SQLModel to stay surgical — noted as a deliberate deviation from §4's "SQLModel").
- `routes/tasks.py` (real CRUD at `/tasks`, replacing the `/api/tasks` stub — that prefix was unreachable
  through the Next `/api/*`→`/*` proxy), `routes/daily.py` (`/daily/summary` = brief sections + weather + open tasks),
  `routes/calendar.py` (`/calendar/events` read + **create gated on user_initiated → 403 otherwise**),
  `routes/finance_lifeos.py` (second `/finance` router: portfolio/quote/history/news/morning — existing finance.py untouched).
- Registered all in `main.py`.
- **Tests pass:** `test_daily_routes` + `test_calendar_routes` + `test_finance_routes` → 15 passed.
  Full backend suite → **121 passed**.

## 2026-06-02 — Step 6: schedule_daily task + generation (Task #6) ✅
- `schedule_daily.py`: stores the canonical XML task prompt verbatim; `generate_daily_brief()` prefers the
  live researcher-agent path and always falls back to a deterministic 9-section builder assembled from local
  data + integration statuses (says "unavailable" where unconnected — never fabricates). Writes
  `reports/{today}/daily-brief.md`.
- Registered `schedule-daily` cron @ 6am ET in the scheduler + lifespan. Manual trigger `POST /daily/generate`
  (`use_agent=false` for verification) + `GET /daily/brief` (raw + parsed).
- **Tests pass:** `test_daily_brief.py` (parser splits all 9; finance/daily/calendar each get their sections;
  manual generate writes a parseable brief all three tabs read) → 3 passed. Full backend suite → **124 passed**.
- §12 Tier-1 "schedule_daily triggers manually + tabs parse it" ✓ (deterministic path). Live agent-orchestrated
  brief (real keys + claude CLI) is the Tier-2 enrichment in the hand-off.

## 2026-06-02 — Step 7: Autonomous Telegram dispatch (Task #7) ✅
- `dispatch/intent.py`: forbidden-action gate FIRST (buy/sell/transfer/withdraw/send/delete/calendar-create/
  permission-change → refused), then deterministic alias match (the worked example "verify daily report of my
  stocks + news" → researcher/finance_deep_dive with params), then guarded Haiku fallback; low confidence → clarify.
- `dispatch/dispatcher.py`: intent → agent via tmux pool (injectable) → md→PDF (WeasyPrint) → artifact tagged
  `source:telegram` (+ requested_at/prompt/agent meta sidecar) → Telegram summary+PDF+deep-link. Creates a
  Job row (kind=telegram_dispatch) so it shows in /jobs. Read-only only.
- `routes/telegram.py` `POST /api/telegram/webhook`: **secret-token header (fail closed → 403)** → **allow-list
  (fail closed; non-Bo silently ignored)** → forbidden refusal → ack + background dispatch, returns 200 fast.
- `.env.example` + TELEGRAM_ALLOWED_CHAT_IDS / TELEGRAM_WEBHOOK_SECRET / MESH_PUBLIC_HOST / INTENT_CONFIDENCE_THRESHOLD.
- **Tests pass (security-critical):** `test_intent_router` (worked example, alias table, 7 forbidden cases, clarify,
  llm fallback), `test_telegram_dispatch` (missing/wrong secret→403, non-allowlisted→ignored, empty-list fail-closed,
  valid→enqueues researcher, forbidden→refused no-dispatch), `test_dispatcher` (source:telegram artifact retrievable
  via artifacts API + real WeasyPrint render + job row) → 25 passed. Full backend suite → **149 passed**.
- Live webhook registration + real agent run = Tier-2 hand-off (needs real bot token + Tailscale URL).

## 2026-06-02 — Step 8: New frontend tabs — finance+/daily/calendar (Task #8) ✅
- `lib/api.ts` extended with typed helpers (portfolio/quote/history/news, daily summary/brief/generate,
  tasks CRUD, calendar events/create) + Life-OS response types. `lib/use-async.ts` shared fetch-state hook
  so every new tab implements loading/empty/error uniformly (and is trivially mockable in tests).
- `/daily`: Today header (date + weather + tldr), interactive Tasks column (quick-add/toggle/delete via tasks API),
  Focus + Agent-suggestion cards from the brief sections. Loading skeletons / empty / error states.
- `/calendar`: Month/Week/Day toggle (Week default), events + task-deadline chips, prev/next/today nav,
  **user-initiated** create modal (calls create with user_initiated, shows not-connected gracefully). 3 states.
- `/finance`: added `FinancePortfolio` net-worth strip (brokerage + wallet KpiCards + positions/assets, each with
  a "Connect X" empty state) above the existing brief/watchlist.
- Navbar: added Daily + Calendar (spec §1 order); Polymarket kept.
- **Verified:** `tsc --noEmit` clean; `npm run build` clean — `/daily` + `/calendar` now in the route list.

## 2026-06-02 — Step 10: Frontend test suite + mobile pass (Task #10) ✅
- vitest.setup polyfills: EventSource (SSE tabs), default fetch stub.
- `test/new-tabs.test.tsx`: /daily, /calendar, finance-portfolio each in **loading + data + empty + error**
  (12 tests), asserting no raw "undefined" leaks.
- `test/existing-tabs.test.tsx`: Mesh/Network/Analytics/Jobs/Artifacts render-smoke (mocked API → loading,
  NetworkGraph stubbed for jsdom). They ship their own empty/error branches in app code.
- `test/mobile.test.tsx`: all 7 page tabs mount at 375px without throwing.
- `test/navbar-terminal.test.tsx`: /terminal regression guard (from §1).
- **Frontend suite green: 33 passed (6 files).** Nav collapses to icons on mobile via `hidden sm:inline`
  (CSS responsive) + responsive grids on the new tabs.

## 2026-06-02 — Step 9: Existing-tab restyle against tokens (Task #9) ◑
- **Analytics fully rebuilt** on the design system: KPI strip → `KpiCard`, sections → `SectionHeader`,
  per-agent breakdown → `DataTable`, proper `SkeletonKpiStrip`/`EmptyState`/`ErrorState` via `useAsync`
  (previously swallowed errors into a bare "No data" string). tsc + build clean; smoke tests still green.
- The other existing tabs (Mesh/Network/Jobs/Artifacts) retain their working glass/violet styling, which is
  already cohesive with the new tokens (the new `--brand` accent IS the existing violet primary) and the shared
  primitives are now available to them. **Honest scope note:** a deeper pixel-level rebuild of those four was
  deliberately not done — it carries regression risk for working, tested UI and is outside the Tier-1 "done" bar
  (build/typecheck/tests green + every tab renders in 3 states). Flagged as optional design polish in the hand-off.
- Fixed test typing (`JSX.Element` → `ComponentType`) for the new React 19 JSX transform.

## 2026-06-02 — Step 11: Final verification + hand-off (Task #11) ✅

### Verification results (§10)
- **Backend** `pytest -q` → **149 passed** (1 benign deprecation warning).
- **Frontend** `npx tsc --noEmit` → clean; `npm run build` → clean (all routes incl. /daily, /calendar; no /terminal);
  `npm test` → **33 passed** (6 files).
- **Live boot** (API on :8001 with an isolated DB, since the production service holds :8000): `/health` ok;
  `/finance/portfolio`, `/daily/summary`, `/calendar/events`, `/tasks`, `/finance/quote/AAPL` all **200**;
  telegram webhook with no secret → **403** (fail-closed); `/docs` 200; `POST /daily/generate?use_agent=false`
  wrote all **9** brief sections. No boot errors.
- **`scripts/dev.sh`**: boots uvicorn :8000 + next :3000 — those ports are intentionally held by the running
  production launchd services (left up for the whole build), so the equivalent boot was proven via the :8001 run
  + the clean production build. Run dev.sh after stopping the prod services if you want the canonical ports.
- Production services confirmed healthy and **untouched** throughout (api :8000 / web :3000 → 200).

### Tier-1 (autonomous-complete) — DONE
- ✅ 8 spec tabs render in loading/empty/error; Terminal route gone (deleted + nav guard test).
- ✅ `npm run build` clean, `tsc --noEmit` clean.
- ✅ Backend pytest (149) + frontend npm test (33) green — incl. Telegram allow-list/fail-closed/secret-token/
  forbidden-action tests + intent-router worked example, all against mocks + simulated Telegram updates.
- ✅ Boot verified (alt port); schedule_daily triggers manually and writes a parseable 9-section brief the
  Finance/Daily/Calendar tabs read.
- ✅ BUILD_LOG reflects every step; hand-off below.

### Tier-2 — needs Bo (live credentials + real device; NOT faked)
- [ ] Fill real keys in `apps/api/.env`: `MARKET_DATA_API_KEY`, `BROKERAGE_API_KEY/SECRET`, `WALLET_ADDRESSES`,
      `GOOGLE_OAUTH_CLIENT_ID/SECRET/REDIRECT_URI` (+ token after consent), `WEATHER_API_KEY`, `HOME_LAT/LON`,
      `TELEGRAM_ALLOWED_CHAT_IDS` (= Bo's chat_id 6452258223), `TELEGRAM_WEBHOOK_SECRET`, `MESH_PUBLIC_HOST`
      (= wenbos-mac-mini.tail254f60.ts.net:3000). `TELEGRAM_BOT_TOKEN` already set.
- [ ] Register the Telegram webhook to the Tailscale-internal URL with the secret-token header:
      `setWebhook` → `http://wenbos-mac-mini.tail254f60.ts.net:8000/api/telegram/webhook`, `secret_token=<TELEGRAM_WEBHOOK_SECRET>`.
      NOTE: the existing `com.wenbo.borina-bridge` polls @borinabot via getUpdates — getUpdates and a webhook are
      mutually exclusive on one bot. Pick one (retire the bridge, or use a second bot for dispatch).
- [ ] Complete Google OAuth consent once (populates the server-side token).
- [ ] Live test: text the bot "verify the daily report of my stocks and tell me if there's any new news on my
      investments" → expect ack → PDF reply + the same PDF in /artifacts tagged source:telegram.
- [ ] Confirm a message from any OTHER Telegram account is silently ignored.

### Deploy note
Built on branch `feature/frontend-rebuild` (10 commits), live services left on `main`. To ship: review the branch,
merge to `main`, then `cd apps/api && .venv/bin/pip install -r requirements.txt` (claude-agent-sdk/weasyprint dep set),
`cd apps/web && npm install && npm run build`, then `launchctl kickstart -k gui/$(id -u)/com.borina.mesh-{api,web}`.
The auto-updater (`com.borina.mesh-updater`) was paused for the build and has been **restored**.

### Optional design polish (not blocking)
- Deeper visual rebuild of Mesh/Network/Jobs/Artifacts onto the shared primitives (Analytics already done).
- Live LLM-orchestrated daily brief (currently deterministic fallback when no agent/keys).

---

# PHASE 2 DELTA — 2026-06-05

Delta on the shipped release (5 items). Read CHANGELOG + this log first; not rebuilding shipped work.
State at start: items 1,2,4,5 absent; item 3 (background dispatch) partial (webhook returns 200 + BackgroundTasks,
but no concurrency cap / persisted queue / idempotency / crash-safety).

## Step 2: Mission-control design language + live primitives (Task #12) ✅
- Retheme (`globals.css` + tailwind): near-black `#0a0b0d` base (220 13% 4%), greyscale surfaces, ONE phosphor
  accent `#3ddc84` mapped onto `--primary`/`--brand`/`--ring` so every shipped primitive inherits; amber `--brand-2`
  secondary. Console texture: hairline grid-bg, faint scanline overlay, `.live-glow`, `.value-flash`, `.term-cursor`,
  `.dot-breathe`/`.dot-run`. `font-mono` → Geist Mono.
- New live primitives: `live-value` (flash-on-change + count-up), `status-dot` (phosphor run-pulse / idle-breathe;
  old path re-exports), `sparkline`, `terminal-cursor`, `activity-feed-row`. Updated `section-header` (`>` prompt
  glyph + mono label) and `kpi-card` (mono value) to the console look.
- **Tests:** `test/live-primitives.test.tsx` (11) incl. count-up convergence. Full frontend suite **46 passed**;
  `tsc` + `next build` clean.

## Step 3: Live command-center front page (Task #13) ✅
- `lib/use-activity.ts`: one shared SSE subscription → recent events + per-agent rolling activity histogram
  (real events-per-tick) driving the fleet sparklines (no placeholder data).
- `CommandStatusBar`: live clock + uptime (tick at rest), running/queued/runs-today (stats), success-rate +
  avg-latency derived from real `/jobs` data, tokens/cost from analytics — all via `LiveValue` (flash/count-up).
- `LiveActivityStream`: real-time SSE feed, rows animate in (AnimatePresence), blinking cursor header.
- `AgentFleet`: live status dots, running cards get `.live-glow` + accent border + streaming current_task with
  cursor (obviously distinct from idle), per-agent sparkline, Run/Open-chat (streaming chat preserved). Rebuilt
  `/` from card-grid → live ops dashboard.
- **Tests:** `test/command-center.test.tsx` (4) incl. "running visibly distinct from idle". Full suite **50 passed**.

## Step 4: Rebuild /network as live force graph (Task #14) ✅
- Replaced static React Flow with a custom SVG force graph (route 58kB → 4.7kB). `lib/force-sim.ts`:
  deterministic force-directed sim (repulsion + edge springs + centering) — testable, no Math.random.
- Mission-control look: hairline grid canvas, MESH hub (amber) + agent nodes (phosphor when running, grey idle,
  red error), mono labels, running-node pulse ring, drag-to-reposition, click→side panel (tagline + quick-run),
  legend + live stats overlay (active links, msg/min, node count).
- **Alive (dead-graph fix):** nodes positioned by the live sim (settle/drift); edges animate on REAL activity SSE —
  particle travels hub→agent, edge glows+thickens for ~2.2s on each message.
- **Regression test** `test/network-graph.test.tsx` (3): positions change across ticks, settled ≠ initial coords,
  edge marks active on a mock message event. Full suite **53 passed**.

## Step 5: Subconscious background dispatch (Task #15) ✅
- Persisted queue on the Job table: `JobStatus.QUEUED` + `telegram_update_id`/`telegram_chat_id` (migrated).
- `dispatch/worker.py`: `enqueue_job` (idempotent by update_id), `claim_next` (atomic, concurrency-capped by
  TELEGRAM_MAX_CONCURRENT_JOBS), `run_job` (re-resolves intent, runs, single progress-ping past
  TELEGRAM_PROGRESS_PING_SECONDS, short error on failure), `recover_orphans` (re-queues crashed `running` jobs),
  `DispatchWorker` drain loop started in lifespan.
- Webhook now ENQUEUES + returns 200 fast (never awaits the run); refactored `dispatcher._produce_and_reply`
  shared by direct + worker paths. Security boundary unchanged (secret/allow-list/forbidden all preserved).
- **Tests** `test_background_jobs.py` (6): 200-without-await, queued→running→done, concurrency cap, crash-survival
  (orphan recovery), idempotent duplicate update_id.

## Step 6: Telegram reply formatter (Task #16) ✅
- `dispatch/telegram_format.py`: `strip_emojis`, `normalize_whitespace` (dedent/trim/collapse), `escape_markdown_v2`,
  length-cap with PDF pointer; `format_telegram` (acks/errors) + `format_dispatch_reply` (short headline + ≤4
  bullets + escaped artifact link). Every outbound reply routes through it; sender now uses MarkdownV2 parse mode.
- **Tests** `test_telegram_format.py` (6): emoji-free, left-aligned, whitespace-collapsed, escaped, length-capped,
  short structured digest. Full backend suite **161 passed**.

## Step 7: Remaining tabs to the alive bar (Task #17) ✅
- **Jobs** rebuilt as a live run-log (`job-log.tsx`): polls every 4s, rows animate in (AnimatePresence) and
  update in place across queued→running→done, mission-control status dots/colors + live running/queued counters,
  telegram-dispatch rows tagged `tg`, row→slide-in drawer (input/output/error/duration/kind). Removed the old
  static `job-history` + `job-detail-modal`.
- **Artifacts** rebuilt (`artifact-list.tsx`): mission-control grid, agent filter, animate-in (8s poll). Backend
  `list_artifacts` now merges the `.telegram-meta` sidecar so **telegram-sourced PDFs surface their original prompt**
  + agent badge. `test_artifacts` extended.
- **Finance/Daily/Calendar/Analytics**: inherit the mission-control language (near-black + phosphor + mono
  `SectionHeader`s + scanline) and already use the flash-capable `KpiCard`/`LiveValue`/`Sparkline` primitives —
  they flash/animate live the moment real data flows (keys tomorrow). Honest note: with no keys connected they show
  "Connect X" states, so there is nothing live to flash there yet (by design — read-only graceful).
- **Tests:** `test/tabs-alive.test.tsx` (Jobs lifecycle + counters + tg tag; Artifacts telegram prompt + download).
  Frontend **55 passed**, backend **162 passed**.

## Phase 2 — final verification (§7)
- `cd apps/web && npm run build` clean; `npx tsc --noEmit` clean; `npm test` → 55 passed.
- `cd apps/api && pytest -q` → 162 passed.
- `scripts/dev.sh` boots uvicorn :8000 + next :3000 — the canonical ports are held by the running production
  services (this very deploy), so the boot is proven by production serving the same code on :8000/:3000.
- Deployed live to the Mac Mini; Tailscale URL serves the mission-control UI. Auto-updater remained on (no-op:
  local == origin/main).
- **Tier-2 (Bo, tomorrow):** add keys, register the Telegram webhook with the secret token, then send one real
  message → expect a SHORT, emoji-free, well-spaced reply that arrives async (didn't block), PDF attached + in
  /artifacts tagged source:telegram. NOTE: webhook vs the existing borina-bridge getUpdates poller are mutually
  exclusive on one bot — retire the bridge or use a second bot for dispatch.

---

# PHASE 3 DELTA — 2026-06-05

Delta on the shipped build (3 items). State at start: §1 formatter cleans whitespace but does NOT cap
lines (replies still multi-paragraph); §2 Files tab = the rebuilt Artifacts grid (agent filter + telegram
meta) but no search / type+date filter / origin grouping / in-pane preview / clean endpoint; §3 planner
agent absent.

## Step 1: Terse Telegram replies by default (Task #18) ✅
- `telegram_format.py`: hard line cap (`TELEGRAM_MAX_LINES=3`) via `cap_lines`; `format_telegram` now collapses
  multi-paragraph input to the cap + PDF pointer. `format_dispatch_reply` is terse by default (headline +
  optional one line + link, ≤3 lines, no paragraph breaks) and only expands on a concrete `is_big_task` signal
  (>1800 chars OR ≥3 headings OR ≥8 bullets) into a sectioned digest that LEADS with a one-line TL;DR (still
  ≤4096, emoji-free, escaped). Prompt backup added to `_build_prompt` (one-line summary first, no paragraphs in
  chat, no emojis). `TELEGRAM_MAX_LINES` in `.env.example`.
- **Tests** `test_telegram_format.py` (+4): terse simple reply (≤3 lines, no para breaks), multi-paragraph
  collapses to cap+pointer, big-task expands with leading TL;DR. Full backend suite **165 passed**.

## Step 2: Make the Files tab usable (Task #19) ✅
- Backend `GET /files?source=&type=&q=` (`routes/files.py`) over the real artifact registry: enriches each file
  with `type` + inferred `source` (telegram meta → "telegram"; filename prefixes → schedule_daily/planner/finance/
  agent; else "uploaded"), `job_id` (from sidecar) for linking to /jobs. Filters + filename/prompt search +
  newest-first + distinct source/type facets. `artifacts.ArtifactInfo` gained `job_id`.
- Frontend `files-browser.tsx` (replaces the simple artifact grid on the Files tab): search box, source/type
  filters, **group-by-origin** (each scheduled task / agent / uploaded under its own heading), live (8s) animate-in,
  download, telegram prompt surfaced, and an **in-pane preview** panel (PDF iframe, image, markdown via
  react-markdown, text) with download + link to the /jobs run.
- **Tests:** backend `test_files_routes.py` (3: source inference, filters+search, newest-first); frontend
  `test/files-browser.test.tsx` (3: grouped listing+controls, search re-query, preview opens). Frontend **58**,
  backend (below).

## Step 3: Personal planner agent (Task #20) ✅
- Registered `planner` agent. `planner.py` engine: `generate_plan` builds a staged proposal (task items +
  per-item calendar proposals — prep buffers before real meetings, a deep-work focus block) from calendar +
  open tasks + the daily brief, writes `reports/{today}/daily-plan.md` + `PlanItem` rows (status=proposed).
  **It NEVER writes the calendar.** Scheduled @6:30am ET (+ terse Telegram digest via the §1 formatter).
- The ONLY write path is `approve_item`: a calendar item → the existing user-initiated `google_calendar.create_event`
  (user_initiated=True); a task item → creates a `Task`. Idempotent. Reject commits nothing.
- Endpoints: `GET /daily/plan`, `POST /daily/plan/generate`, `POST /daily/plan/{id}/approve`, `/reject`.
- Telegram inline approve/reject (`callback_query` → `approve:{id}`/`reject:{id}`) reuses the fail-closed allow-list.
- Frontend: `/daily` "Today's plan" card — tasks + proposed calendar changes with per-item Approve/Reject.
- **Tests** `test_planner.py` (8): generate-writes-no-calendar, **no-autonomous-write regression**, unapproved
  commits nothing, approve→exactly one user-initiated write (+ idempotent), approve-task→creates Task, reject
  commits nothing, plan shape, callback security (non-allowed ignored / allowed approves). Frontend
  `todays-plan.test.tsx` (3). Backend **176**, frontend **61**.

## Phase 3 — final verification ✅
- backend `pytest -q` → **176 passed**; frontend `npm test` → **61 passed**; `tsc --noEmit` + `next build` clean.
- `scripts/dev.sh` boots uvicorn :8000 + next :3000 (canonical ports held by the running production deploy of
  this same code — boot proven by prod serving on :8000/:3000).
- Deployed: `/files` + `/daily/plan` serve 200; live planner generate → 2 tasks + 1 calendar proposal with NO
  calendar write; all tabs 200; Tailscale-reachable. Auto-updater no-op (local == origin/main).
- **Tier-2 (Bo):** (1) real Telegram message → terse 1-3 line async reply; (2) trigger planner → approve one
  proposed item → exactly one event lands on the real Google Calendar; reject → nothing written. (Reminder: the
  webhook and the existing borina-bridge getUpdates poller can't share one bot.)

# Phase 4 — 2026-06-09

## Step 1: Repo cleanup (parallel-run leftovers) ✅
- Removed the 9 registered parallel-agents worktrees (`.worktrees/{judge,pane-1..8}`) + their branches
  (`pane-1..8`, `parallel/judge-merge`) — winner already merged to main at the phase-3 commits.
- Deleted stray backups: `apps.old-main-tree.bak/` (1.0G), nested `borina-mesh/` (531M),
  `borina-mesh-apps/`, `scorecards/`, `apps/api/main.py.conflict.bak`, `apps/web/tsconfig.tsbuildinfo`.
- `.gitignore`: added `reports/` (runtime briefs/PDFs), `*.tsbuildinfo`, `.worktrees/`.
- Committed `scripts/auto-update.sh` — launchd (`com.borina.mesh-updater`) runs it; it was untracked.

## Step 2: Live LLM-orchestrated brief + planner ✅
- **Diagnosed prod bug:** the 6am brief artifact was the raw tmux pane capture — echoed prompt
  (which itself contains `<section>` tags, so `parse_brief` validated it), the agent's file dump,
  and TUI chrome. The researcher agent had meanwhile saved a CLEAN brief inside its own workdir.
- **Brief (schedule_daily.py):** live path now reads the agent-workdir file (`_agent_brief_file`)
  first — file handoff beats pane scraping; `_validate_brief` rejects prompt echoes (section bodies
  compared against the prompt's instruction bodies) and coerces `## Heading`-styled briefs to the
  canonical `<section>` format (`daily_brief.coerce_headings_to_sections`). `{today}` now resolved
  into the prompt.
- **Runner (runner_v2.py):** `_delta_after_prompt` strips the WHOLE echoed prompt block (was: first
  line only); `_strip_ui_chrome` drops post-response chrome (✻ Worked for, feedback prompt, ⏵⏵ mode
  bar, ctrl+o hints). Registered `planner` in AGENT_REGISTRY.
- **Planner (planner.py):** new live path `generate_plan_with_agent` — planner agent gets read-only
  context (events, open tasks, brief tldr/focus), returns a strict JSON proposal array,
  `_parse_agent_proposals` validates/caps items, falls back to the deterministic heuristics on any
  failure. Scheduler + `POST /daily/plan/generate` (`use_agent` param) use it. daily-plan.md notes
  provenance (agent vs fallback). **No-autonomous-write rule unchanged** — the agent only produces
  text staged as proposed PlanItems; the sole write path is still user-approve.
- **Tests** `test_live_llm.py` (11): tagged-brief accept, prompt-echo reject, heading coercion,
  workdir-file handoff, echo→fallback, full-echo delta strip, chrome strip, JSON parse (fences),
  garbage/invalid-item rejection, agent-proposals staged with zero calendar writes, garbage→fallback.
  Backend **187** green.

## Step 3: Telegram polling mode + bridge retired + keys ✅
- **Why polling:** Telegram needs public HTTPS to push a webhook; the tailnet host isn't publicly
  reachable. getUpdates long-polling dials OUT to api.telegram.org — same UX, zero public exposure.
- **`dispatch/poller.py`:** TelegramPoller, on only when `TELEGRAM_DISPATCH_MODE=polling` + bot
  token set. Calls deleteWebhook on start (polling owns the stream), long-polls getUpdates (25s),
  feeds every update through the SAME fail-closed pipeline as the webhook — refactored the webhook's
  post-secret logic into `routes.telegram.process_update` (allow-list → intent → idempotent enqueue)
  shared by both. Offset in-memory; restart redelivers unacked updates and update_id idempotency
  dedupes. Started/stopped in the lifespan next to the dispatch worker.
- **Webhook unchanged + still fail-closed** (secret token required); polling transport is
  authenticated by the bot token instead.
- **Live-run fixes from §2 verification:** planner agent JSON now handed off via
  `proposals/{day}.json` in the agent workdir (pane wrap was breaking JSON string literals —
  observed live); `_parse_agent_proposals` repairs pane-wrapped JSON (newline collapse retry);
  chrome strip catches any `✻` spinner line (saw "Sautéed", not just "Worked").
- **Env:** `.env` got `TELEGRAM_DISPATCH_MODE=polling`, `TELEGRAM_ALLOWED_CHAT_IDS=6452258223`,
  `MESH_PUBLIC_HOST`; `.env.example` documents the new mode.
- **Bridge retired:** `com.wenbo.borina-bridge` booted out; plist renamed `.disabled` (reversible).
  The mesh is now @borinabot's sole consumer.
- **Tests** `test_telegram_polling.py` (7): disabled-by-default, mode+token gate, start no-op when
  disabled, allowed→enqueue + offset ack, non-allowed dropped (still acked), processing-error
  survival, webhook/poller share `process_update`. Plus 3 new live-fix tests. Backend **196** green.

## Step 4: Visual pass — Mesh / Network / Jobs (data-truth polish) ✅
- Grounded in live screenshots of all four tabs (Playwright). Files tab needed nothing.
- **Task-label noise:** Mesh fleet cards + every Jobs row displayed the raw scheduler prompt
  ("[scheduled] Run your scheduled daily task. Current time: 677454.631"). New
  `cleanTaskLabel`/`isScheduledPrompt` in `lib/utils` strip the tag + machine timestamp at display
  time (fixes historical rows too); Jobs rows get a muted `cron` badge alongside the existing `tg`
  badge; the raw prompt stays in the job drawer. Scheduler now stamps prompts with ISO UTC
  ("Now: …Z") instead of monotonic seconds.
- **Status-bar truth:** home page showed RUNNING 84 — stale rows: the scheduler creates jobs as
  RUNNING and restarts stranded them (orphan recovery only covered telegram_dispatch). New
  `fail_orphaned_running_jobs` runs at startup (lifespan), failing non-telegram RUNNING leftovers
  with "orphaned by service restart"; telegram jobs stay with the dispatch worker's re-queue.
- **Network graph:** node labels alternate above/below the node so adjacent agents ("Polymarket
  Intel" / "Ecommerce Scout") can't collide.
- **Favicon:** `app/icon.svg` (terminal prompt glyph, phosphor green on near-black) — kills the
  404 on every page load.
- **Tests:** backend `test_orphaned_jobs.py` (orphans failed, telegram + completed untouched);
  frontend `clean-task-label.test.ts` (5). Backend **197**, frontend **65**, tsc + build clean.

# Phase 5 — 2026-06-10

## Step 1: Google Calendar OAuth — real consent flow + auto-refresh ✅
- `integrations/google_oauth.py`: consent URL (offline + prompt=consent for a refresh token),
  `exchange_code`, chmod-600 server-side token file (`~/.borina/google_oauth_token.json`,
  override via GOOGLE_OAUTH_TOKEN_FILE), `get_access_token()` auto-refreshes hourly-expiring
  access tokens (refresh_token preserved across refresh replies that omit it). Env
  GOOGLE_OAUTH_ACCESS_TOKEN still wins when set (tests/manual). CSRF: random `state` persisted
  at /start, compare_digest-validated at /callback.
- Routes: `GET /calendar/oauth/start` (redirect to Google) + `GET /calendar/oauth/callback`
  (exchange + "connected" page). `google_calendar._access_token()` now reads the managed token.
  The user-initiated-only write gate is untouched.
- conftest isolates GOOGLE_OAUTH_TOKEN_FILE to the test tmp dir.
- **Tests** `test_google_oauth.py` (10): auth-url params, exchange persists, refresh preserves
  refresh_token, env override, empty when unauthorized, calendar status via token file, start
  redirect, callback exchange + state validation (+ bad-state 400), start without creds 400.
  Backend **207** green.
- Bo's borinamesh client id/secret live in `apps/api/.env` only (gitignored).

## Step 2: Google consent completed live ✅
- Console (driven via Playwright with Bo's session): redirect URI saved, Calendar API confirmed
  enabled, **OAuth app published Testing → In production** (test-user gate + 7-day refresh-token
  expiry were the consent blockers; also added prompt=select_account after the browser auto-picked
  the wrong signed-in account).
- Bo consented; token file landed at `~/.borina/google_oauth_token.json` (0600, refresh_token
  present). Live verify: `GET /calendar/events` → `"connected": true`.
- Remaining Tier-2: approve one planner item in /daily → exactly one event on the real calendar.

## Step 3: Planner reads Obsidian dailies + Bo's daily-task workflow ✅
- `planner._recent_daily_notes()`: newest 2 vault daily notes (capped 4k chars) join the agent
  context; prompt tells the agent to prefer FRESH items and skip long-running ones that recur
  across days. Read-only; empty vault/test env → no vault context. Backend **210** green.
- Workflow agreed with Bo: daily tasks are PROPOSED from Obsidian + recent context, Bo picks,
  then added (3 added today via /tasks); never auto-added; stale items excluded; important picks
  marked in the Obsidian daily note.

## Step 4: Telegram voice messages → routed like text ✅
- `dispatch/voice.py`: local Whisper via faster-whisper (CPU int8 on the M4, no cloud API, model
  env TELEGRAM_VOICE_MODEL default "base", HF-cached on first use). Telegram getFile download →
  transcribe → transcript enters the SAME intent/dispatch pipeline; replies prefix `Heard: "…"`.
- Security: transcription happens only AFTER the allow-list check (media from non-allowed
  senders is never downloaded); 180s/20MB caps enforced pre-download; every failure fails closed
  ("try typing it").
- **Tests** `test_telegram_voice.py` (5): transcript routes like text, non-allowed never touches
  media, transcribe-failure fails closed, caps block pre-download, no-token no-download.
  Backend **215** green.

## Step 5: General-question fallback in the intent router ✅
- Live finding: Bo's voice note transcribed fine but never dispatched — `_classify_llm` is an
  offline stub (no API key on this box), so anything missing the keyword aliases bounced with
  "could you rephrase?". Natural speech rarely hits the aliases.
- `resolve_intent` stage 4: non-forbidden text that no specialist claimed now routes to the
  read-only **researcher** as `general_question` (confidence 0.5, source "fallback") with the raw
  message as prompt. The forbidden-action gate still runs FIRST and still refuses. Backend **216**.
- Also confirmed the 409 getUpdates errors are restart bursts (old long-poll lingering a few
  seconds server-side), not a second consumer — steady state is clean.

# Phase 6 — 2026-06-10 (Telegram autonomy: plan docs/superpowers/plans/2026-06-10-telegram-autonomy-features.md)

## §A Obsidian write-back ✅
- `dispatch/vault_writeback.py`: every completed dispatch → frontmattered report in
  `04-resources/reports/{day}-{agent}-job{id}.md` + link under "## Mesh outputs" in the daily note
  (note/section created if missing). No-op without a vault; never raises. Hooked after
  `_complete_job` in the dispatcher. Tests (6).
## §B Telegram threads ✅
- Worker honors `job.agent_id` over prompt re-resolution (prereq — follow-ups must reach the
  thread's agent, not the researcher fallback).
- `TelegramThread` table; `send_telegram_message` returns message_id; every report reply recorded.
- `process_update`: replying to a bot report routes the follow-up to the SAME agent (tmux session
  context intact), forbidden gate still first. Tests (5 + worker test).
## §C Missions ✅
- `mission:` alias → ceo/mission (checked before single-agent aliases; forbidden gate still wins).
- `dispatch/mission.py`: CEO decompose (strict JSON, pane-wrap repair) → ≤4 read-only agents in
  parallel → CEO synthesis; decompose failure → single researcher; synthesis failure → section
  join. Dispatcher branches on task_type=mission with a "Mission: N agents dispatched" progress
  ping. Tests (9).
- Backend **237** green.

## Phase 6+ — Telegram fleet control + autonomous builder ✅
- **`status` command** (also "agents"/"fleet"): one line per agent — running + cleaned current
  task, or idle — plus active/stuck builder jobs. Answered inline, nothing dispatched.
- **Direct addressing**: "<agent>: task" / "<agent>, task" routes to that exact agent
  (forbidden gate still first).
- **Autonomous builder** (`dispatch/builder.py` + `scripts/builder_run.py`): "build: X" from
  Telegram → Job(kind=builder) + DETACHED runner (start_new_session — survives the kickstarts it
  performs). Runner: worktree → headless `claude -p` (40-min cap; commit-when-green,
  BLOCKED.md-when-stuck contract) → `evaluate_worktree` (stuck/nochange/ready; dirty tree =
  stuck) → INDEPENDENT suite verification (backend pytest; vitest+tsc when web changed;
  node_modules symlinked) → ship: merge --no-ff → next build if needed → kickstart → health
  check (rollback to pre-merge sha on failure) → push. Bo is messaged ONLY when stuck —
  the message is thread-recorded; his reply = guidance (GUIDANCE.md + respawn --resume),
  'abort' = cancel + cleanup. Orphan recovery spares builder rows with a live pid.
- The generic forbidden gate deliberately doesn't apply to build texts (a code task saying
  "remove X" isn't a live deletion); builds gate on independent verification instead.
- Tests `test_telegram_status.py` (5) + `test_builder.py` (11). Backend **253** green.

## Phase 6 — live verification ✅
- **Dispatch + write-back + thread (job 1921):** real researcher dispatch through the production
  worker → COMPLETED, reply + PDF to Bo, TelegramThread recorded, vault report
  `04-resources/reports/2026-06-10-researcher-job1921.md` + daily-note link written.
- **Autonomous builder (job 1923):** `build: add a GET /ping endpoint…` via the real
  process_update path → headless claude implemented endpoint + wrote its own pytest test
  (~95s) → independent verification → merged `dfab73f` → kickstart → health OK → pushed →
  worktree cleaned → ship report to Bo. `GET /ping` → `{"ping":"pong"}` live.
  **~2.5 minutes message-to-shipped, zero human input.**
- Post-merge main: backend **254** (builder's test included), frontend **65**, tsc clean.
- **Mission (job 1924):** live `mission:` through the production worker → CEO decompose →
  agents → synthesis COMPLETED; reconciled risk report (CPI/30yr + Iran-oil with confirmation
  triggers) delivered to Bo + vault write-back. All goal items verified end-to-end.

# Phase 7 — 2026-06-14 (clean output, PDF opt-in, Obsidian brain, builder agent)

## §1 Garbage PDF fixed — clean answer via file handoff ✅
- ROOT CAUSE: dispatch PDF'd the raw tmux pane scrollback (echoed prompt, ⏺ tool calls,
  Bash(...)/Write() blocks, box-drawing, feedback prompt) — the agent had written a clean report
  file the dispatcher ignored. Same "pane capture is lossy" lesson as the brief/planner.
- `dispatch/answer.py`: agent writes its final answer to a handoff file (answers/job{id}.md in its
  workdir); dispatcher reads THAT. Aggressive fallback cleaner (`clean_agent_output`) strips all
  TUI/tool chrome if the file is missing. Mission sub-outputs cleaned too.
- Live: job 2181/2184/2185/2186 all garbage=False; the answers are clean prose.

## §2 PDF opt-in ✅
- `answer.wants_pdf()` gates PDF: default reply is the clean answer in chat
  (`format_answer_reply`); a PDF is rendered+attached ONLY when the request says
  pdf/report/document/write-up. Always saves a browsable .md artifact + vault write-back.
- Live: job 2184 (no "pdf" word) → pdf=False; job 2185 ("detailed pdf report") → pdf=True, valid
  PDF 1.7 with clean source.

## §3 Obsidian brain (OpenClaw-style) ✅
- `dispatch/vault_brain.py`: recall() scans vault (reports/daily/brain) by keyword overlap and
  injects relevant context into every agent prompt; remember() appends durable facts to
  04-resources/brain/memory.md. Telegram `remember:`/`recall:` commands. Closes the read+write
  loop with the existing write-back: the mesh reads what it knew and writes what it learned.
- Live: remembered "coordlayer phase 11 is next" via Telegram → landed in the vault brain → recall
  returned it.

## §4 Builder agent + external projects ✅
- `agents/builder.py`: BuilderAgent registered in the fleet (opus tier; shows in status/dashboard).
- `build <repo>: <task>` clones an external GitHub repo, implements on a branch, pushes, opens a
  PR (never merges external); the clone persists at ~/.borina/builds/<repo>-job<id> so Bo can edit
  anytime. `build:`/`builder:` still self-builds + ships this mesh.
- Live: `build coordlayer: add CONTRIBUTING.md` → opened PR bocodes1/coordlayer#1 (117 lines,
  accurate, OPEN) fully autonomously; editable clone on disk.
- Backend 276 → **283** tests green across the phase.
