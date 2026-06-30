# Borina Mesh — Efficiency & Usefulness Overhaul (Design)

- **Date:** 2026-06-27
- **Status:** Approved for planning (brainstorming complete)
- **Branch:** `feature/os-efficiency-overhaul`
- **Source:** 12-agent code audit + 10-tab visual sweep (2026-06-27). Every claim below is backed by a `file:line` from that audit.

## Problem

The OS is bloated and burns LLM quota producing output the operator (Bo) never reads:

1. **Credit waste.** ~120–130 LLM agent runs/day, ~62 of them **Opus**, and ~48 of those Opus calls are reviewing a *bot-health ping*. The morning window (5–8am) fires 6 overlapping jobs producing 3–4 redundant "morning narratives" for the same day.
2. **Unreadable finance brief.** Renders as a wall of raw `| pipe |` text and apologetic "data unavailable" filler, with the wrong date.
3. **Dead tabs / fake metrics.** A broken Polymarket iframe and always-zero token/cost numbers presented as real.

## Root cause: where the cost actually is

The scheduled agents are spawned via tmux **without `--model`** (`tmux_supervisor.py:203`), so they run the CLI default (Sonnet) — the `AGENT_MODELS` Opus labels in `agents/models.py` are **dead code** for cron runs. The **only** guaranteed-Opus recurring call is `QADirector.review()` (`base.py:56`, SDK path), pinned to `claude-opus-4-8` (`agents/models.py:9`), which fires **after every `register_defaults` agent run** (`scheduler.py:494-533`). With `trader` on `*/30` that is ~48 Opus reviews/day of a health-watcher.

Second-order: the roster "retired/parked" gate only filters `register_defaults`; the dedicated `register_finance_brief` / `register_planner` / `register_operator` methods (`main.py:81-85`) fire **unconditionally**, so retired agents (finance, planner) still run.

## Goals

- Cut recurring LLM runs from ~120/day → **~14/day**, and recurring **Opus → 0**.
- Make the finance brief short, correctly-dated, table-rendered, and free of apologetic filler.
- Remove dead weight (Polymarket) and stop presenting fabricated cost metrics.
- Fix the confirmed functional bugs surfaced by the audit.

## Non-goals

- No new data integrations (FRED/Hunter/Microsoft OAuth/on-chain) — out of scope; we stop *pretending* they exist instead.
- No removal of Network or Outreach tabs (operator chose to keep both visible).
- No change to the propose-only / approval-gated safety model (see Invariants).

## Decisions (from brainstorming)

| Decision | Choice |
|---|---|
| Tab cuts | **Remove Polymarket**; **strip fake cost metrics**. Keep Network + Outreach visible. |
| Cron/credit diet | **Aggressive** |
| Finance brief | **Full fix** |

---

## Workstream A — Aggressive credit diet

**A1. Trader health-watcher → non-LLM.** `trader` `*/30` (`scheduler.py:102`) exists to watch a bot; the generic prompt is "Run your scheduled daily task" (`scheduler.py:441`). Replace with a deterministic HTTP/process health check (no agent spawn). If a watcher must stay LLM-based, it does not need 48×/day — but default is **remove the LLM cron entirely** and keep a cheap Python uptime check that only pings Bo on failure.
*Removes ~48 runs + ~48 Opus/day.*

**A2. Remove the Opus QA review from the cron path.** In `_run_agent` (`scheduler.py:494-533`), the post-run `QADirector.review()` is the entire recurring-Opus problem. Decision: **skip QA for scheduled/cron agent runs** (it adds no operator-visible value for a digest/health run). The interactive dashboard-chat QA review (`chat.py:61`, also Opus) stays out of scope here but should be downgraded to Haiku or flag-gated in a follow-up, since it silently doubles the cost of every chat reply. Net effect: recurring Opus → 0.
*Removes ~62 Opus/day.*

**A3. Collapse the morning cluster to ONE 6:30 brief.**
- Delete `operator-morning` phase (`daily_operator.py:74` / `scheduler.py:409`) — it's a byte-for-byte duplicate of the 6:30 planner (`scheduler.py:205`). Keep midday/eod phases (midday optionally demoted to on-demand `/midday`).
- Drop the separate `researcher` 8am cron (`scheduler.py:94`) — researcher already runs 6am via `schedule_daily`.
- Fold the `ceo` 7am "strategic briefing" + `schedule_daily` 6am into the single 6:30 planner brief (the one that sends the Telegram digest Bo reads).
- Strip the permanently-dead sections (markets/calendar/inbox/weather "not connected") from the brief prompt so it stops emitting apology filler.
*Removes ~4 redundant runs + 2 Opus QA/day.*

**A4. Fix the roster-gate bypass.** Make `register_finance_brief`, `register_planner`, `register_operator` honor `active_scheduled_agents` like `register_defaults` does, so retired agents never schedule. (After A3, finance-brief auto-run becomes on-demand per Workstream B; this guards against accidental reactivation.)

**Target ledger after A (keep):** inbox-triage 2h (×12, no QA), one 6:30 morning brief (×1), operator-eod learner (×1), apply-weekly (~3/wk). ≈ **14 runs/day, 0 recurring Opus.**

---

## Workstream B — Finance brief full fix

**B1. Renderer** (`apps/web/components/finance-brief.tsx`):
- Add `remark-gfm` dependency; render `<ReactMarkdown remarkPlugins={[remarkGfm]}>` so tables become real `<table>`s (kills the `| pipe |` wall).
- Add `@tailwindcss/typography`; register it in `tailwind.config.ts` so the existing `prose prose-invert` classes actually style headings/lists/tables.
- Make `POST /brief/regenerate` (`routes/finance.py:88-95`) return `skipped_sections` + `data_source_status` like the GET handler, so the amber banner persists after Regenerate.

**B2. Generation** (`apps/api/agents/finance_brief.py`):
- **Date bug:** inject `screen.trading_date` into the prompt; remove the literal `{{date}}` (`finance_brief.py:82`).
- **Pane-scrape bug:** read the agent's written answer file (the clean handoff pattern already used elsewhere via `dispatch/answer.py`) instead of de-chroming a tmux pane (`finance_brief.py:146-212`).
- **Cost:** short-circuit — when the screen has 0 candidates AND 0 watchlist moves, write a deterministic one-line brief in Python and **skip the LLM entirely**. When it does run, use Sonnet/Haiku (templating numbers, not reasoning); reserve Opus for the on-demand deep-dive only.
- **Trigger:** per A3, the brief is no longer its own 5am cron; it's produced on-demand (`POST /finance/brief/regenerate`) and/or folded into the single morning brief.

**B3. Prompt / format rewrite** (`finance_brief.py:_build_prompt` + the `BRIEF_FORMAT*.md` spec files in `~/.borina/agents/finance/`):
- Replace "say so honestly when empty" with a hard **omit-or-stay-silent** contract: *"Output only sections with real data. Never print an empty section header. Never write 'unavailable', 'not configured', 'I can't compute', or any apology — omit silently. Source-availability is shown elsewhere. If nothing passed, output exactly: `No candidates passed today.`"*
- Convert `BRIEF_FORMAT.md` from a fixed numbered skeleton into **optional blocks** rendered only when their data array is non-empty.
- **Drop crypto from the brief** until an on-chain source exists (the rubric demands NVT/MVRV/flows the screen never gathers) — render BTC/ETH/SOL as a deterministic Python price line, no LLM.
- Align the universe claim with reality (screen the watchlist, don't claim "~3,000 names").

**B4. Drop dead cards** (`apps/web/app/finance/page.tsx`): remove the Portfolio strip (permanently `—`; brokerage/wallet point at `example.com` hosts) and the Calendar card (hard-coded "wired in v2"). Keep the watchlist + per-ticker deep-dive (the genuinely-working, on-demand, real-data pieces).

---

## Workstream C — Remove Polymarket

Delete the tab and all lingering dead code so it can't be reactivated:
- `apps/web/app/polymarket/` + the nav entry (`nav-config.ts:33`).
- `integrations/polymarket.py`, `agents/polymarket.py`, `main.py:27` import, `models.py:8`, `runner_v2.py:40` registry entry, `scheduler.py:93`+`:468`, `fleet_roster.py:27/48/52`.
- The polymarket block in `schedule_daily.py` (`:101/:113/:132-134/:147`) that pings the dead bot and emits "Bot API not reachable" filler.
- The polymarket entries in `dispatch/intent.py:20,157` + `dispatch/mission.py:19`.
- Update/trim tests: `test_integrations.py`, `test_fleet_roster.py`, `test_intent_router.py`, `test_routes.py`, `lib/agent-icons.ts`. Run `pytest` + `tsc` to confirm clean removal.

---

## Workstream D — Strip fake cost metrics

Token/cost are hardcoded `0` everywhere (`chat.py:99-100`, `scheduler.py:550-551`) — no metering exists on the Max subscription.
- **Analytics** (`apps/web/components/analytics-cards.tsx`): remove the "Tokens Used" + "Total Cost" KPI cards and the Tokens/Cost table columns; change the page subtitle (`app/analytics/page.tsx:18`) from "Token usage, costs, and run history" to "Run history and agent activity". Optionally replace with a real free metric (runs/day, last-run-time).
- **Dashboard** (`apps/web/components/command-status-bar.tsx:101-106`): remove the tokens + cost cells from the status bar.

---

## Workstream E — Bug-fix sweep (secondary; "fix all the bugs")

Lower priority than A–D but confirmed and cheap:
- **Files** (`routes/files.py:74,88`): stop calling `list_artifacts()` twice per request; add a `limit`/`since` window (default last 7 days / 200 newest) so the tab doesn't ship all 2,735 PDFs; raise/replace the 8s poll. Fixes the 28k-DOM perf bug.
- **Jobs** (`apps/web/app/jobs/page.tsx:13-16`): delete the "Overnight workers" section (0% success, 25-day stale, null log paths); lead with the working Run log. Optionally paginate `listJobs` (`jobs.py:64`, currently `limit=50`).
- **Calendar** (`routes/calendar.py:40`, `page.tsx:98`): parse both sides of the task-chip window as datetimes (not raw ISO strings); treat all-day date-only starts as local-midnight to fix the −04:00 day-shift.
- **Network** (`network-graph.tsx:35`): poll `listAgents` (or reuse the activity stream) so node status isn't a stale mount-time snapshot; delete the dead `routes/threads.py` stub.
- **Dashboard** (`command-status-bar.tsx:64` + `agent-fleet.tsx:112`): de-dupe the two independent `/agents` polls into one shared source.

---

## Safety invariants (must not weaken)

- Telegram webhook stays fail-closed (secret-token + chat-id allow-list).
- Dispatch + planner remain **propose-only**; calendar writes ONLY on explicit `user_initiated=True` approval (the planner no-autonomous-write regression test must stay green).
- Removing crons/QA must not introduce any autonomous write path. The morning brief stays a *proposal* surface.

## Testing

- Backend `pytest` (~493 currently green) + frontend `vitest` must stay green after each workstream; update tests touched by C/D rather than deleting coverage.
- Add: a test that the morning brief prompt contains no apology directive and omits empty sections; a test that scheduled agent runs do **not** trigger QA; a renderer test that a markdown table produces a `<table>`.
- Manual verification via Playwright on localhost:3000 for the finance brief render + each touched tab before deploy.

## Rollout

Single branch `feature/os-efficiency-overhaul`, workstreams as separate commits (A, B, C, D, E) for reviewability. Deploy per the standard path: merge → `cd apps/web && npm run build` → `launchctl kickstart -k gui/$(id -u)/com.borina.mesh-{api,web}`. Do not restart mid-build.

## Open questions

- Morning brief: keep the 6:30 Telegram digest as the single delivery, or also surface in the Daily tab only? (Lean: both read the same cached artifact — no extra LLM.)
- Trader watcher: drop entirely, or keep a Python uptime ping that messages Bo on failure? (Lean: keep the cheap ping; it's not an LLM cost.)
