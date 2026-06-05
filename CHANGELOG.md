# Changelog

All notable changes to Borina Mesh are documented here.
Format based on [Keep a Changelog](https://keepachangelog.com/); this project
uses date-based releases.

## [2026-06-05] — Phase 2 Delta: Mission-Control UI, Live Graph, Background Dispatch

A delta on the same-day rebuild — making the console feel **alive**.

### Added
- **Mission-control design language:** near-black base with a single phosphor-green
  accent reserved for live signal, monospace data, console texture (hairline grid,
  scanline). New live primitives: `live-value` (flash + count-up), `status-dot`
  (run-pulse / idle-breathe), `sparkline`, `terminal-cursor`, `activity-feed-row`.
- **Live command-center front page:** a status bar with live clock/uptime/stats and
  derived KPIs (success rate, avg latency), a real-time activity stream, and a reactive
  agent fleet where running agents glow + stream their current task (visibly distinct
  from idle).
- **Live `/network` graph:** a custom force-directed simulation (replacing the static
  React Flow graph) — nodes drift and settle, edges fire particles on real agent message
  flow, drag + node panel + live stats. Responsive bottom-nav app shell on mobile.
- **Background Telegram dispatch:** the webhook now enqueues onto a persisted, crash-safe
  queue and returns instantly — concurrent (capped), idempotent by Telegram `update_id`,
  with orphaned-job recovery on restart and a single "still working" progress ping.
- **Live Jobs run-log** (rows animate queued→running→done, row→drawer) and a
  **mission-control Artifacts grid** where Telegram-sourced PDFs surface their original prompt.

### Changed
- Every tab inherits the mission-control look; the 6 shared primitives were upgraded so
  all consumers updated at once.
- All outbound Telegram messages route through one formatter: short digest, no emojis,
  MarkdownV2-escaped, whitespace-normalized, length-capped (detail stays in the PDF).

### Security
- The background/formatting changes preserve the fail-closed webhook (secret-token +
  allow-list) and the read-only-only dispatch rule. Forbidden intents are still refused.

### Notes
- Verified green: backend `pytest` 162, frontend `vitest` 55, `tsc` + `next build` clean.
- Tier-2 (needs real keys + a device): unchanged from the prior release's checklist; send one
  real Telegram message to confirm the async, short, well-formatted reply + PDF in `/artifacts`.

## [2026-06-05] — Frontend Rebuild + Life-OS Tabs + Autonomous Telegram Dispatch

A large release adding three personal "life-OS" tabs, a real integrations
layer, an autonomous (read-only) Telegram dispatch pipeline, a shared design
system, and a full automated test suite (backend + frontend).

### Added
- **Finance tab — portfolio strip:** net-worth view across brokerage + crypto
  wallet, with positions/assets and graceful "Connect X" states when a source
  isn't configured.
- **Daily tab (`/daily`):** Today header with weather, an interactive task list
  (quick-add / toggle / delete), and Focus + Agent-suggestion cards driven by
  the morning brief.
- **Calendar tab (`/calendar`):** Month / Week / Day views (Week default),
  Google Calendar events plus task-deadline chips, and a user-initiated event
  create modal.
- **`integrations/` package:** one read-only provider module each for market
  data, brokerage, crypto wallet, Polymarket, weather, and Google Calendar.
  Every provider degrades to a clean "not connected" object instead of crashing
  a tab, and never raises.
- **`schedule_daily` brief:** a 9-section morning brief written to
  `reports/{today}/daily-brief.md` (markets, watchlist movers, trading,
  calendar, tasks, inbox, nudges, weather…) that the Finance/Daily/Calendar tabs
  read. Runs at 6am ET, or on demand via `POST /daily/generate`.
- **Autonomous Telegram dispatch:** message the bot → intent router → the right
  agent → PDF report back, with the PDF also landing in `/artifacts`
  (`source: telegram`). Strictly read-only intel.
- **Backend endpoints:** tasks CRUD (`/tasks`), `/daily/summary` + `/daily/brief`,
  `/calendar/events` (+ user-initiated create), and finance
  `portfolio` / `quote` / `history` / `news`.
- **Design system:** surface/semantic color tokens and six shared UI primitives
  (`kpi-card`, `section-header`, `data-table`, `empty-state`, `error-state`,
  `loading-skeleton`).
- **Tests:** isolated `pytest` harness + new backend suites (integrations,
  routers, intent router, dispatcher, Telegram security); a brand-new frontend
  Vitest/RTL harness covering every tab in loading/empty/error + a mobile pass.

### Changed
- **Analytics tab** rebuilt on the design system (KPI cards, shared table,
  proper loading/empty/error states).
- `.env.example` extended with all new integration + Telegram-dispatch keys.

### Removed
- **Terminal tab** removed entirely (route, nav item, imports) with a regression
  guard so it stays gone.

### Security
- Telegram webhook is **fail-closed**: it validates a secret-token header
  (rejects on mismatch/absence) and an allow-list of chat IDs (an empty or
  misconfigured list rejects everyone). Auto-dispatch only ever runs read-only
  research/intel agents — any message whose intent maps to a trade, transfer,
  send, delete, calendar-create, or permission change is refused, not executed.
- Calendar event creation is gated on an explicit user-initiated request; no
  agent path can create events. No credentials are written to the frontend,
  logs, or URLs.

### Notes
- **Tier-2 (needs real keys + a device):** fill provider keys in
  `apps/api/.env`, register the Telegram webhook to the Tailscale-internal URL,
  and complete Google OAuth once. See `BUILD_LOG.md` for the full hand-off
  checklist. The app runs fully without these — tabs just show "Connect X".
- Verified green at release: backend `pytest` 149 passed, frontend
  `vitest` 33 passed, `tsc --noEmit` + `next build` clean.
