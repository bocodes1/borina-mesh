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
