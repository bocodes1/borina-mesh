# Borina Mesh — Autonomy Layer (L2/L3/L4) Design

**Date:** 2026-06-18
**Status:** Approved design (follows the foundation slice L0+L1)
**Depends on:** `2026-06-18-foundation-lean-fleet-clean-remote-design.md`

Three layers turn the foundation (L0/L1) into a delegatable staff member: a **proactive day** that plans and runs your calendar/tasks under approval (L2), a **long-goal runner** that decomposes and grinds multi-day objectives with check-ins (L3), and a **self-managing fleet** that prioritizes its own queue and parks idle agents (L4). Each builds *on* the foundation rather than beside it: every steering surface is a `Card` with inline buttons, every cadence is a DB-backed schedule on the existing scheduler, and every long-runner copies the builder's detached-spawn pattern. The result is a system you talk to in one channel that proposes constantly and writes only when you tap.

## Foundation reality check

The L0/L1 slice this spec assumes — `AgentConfig.state ∈ active|parked|retired`, the `Card{headline,lines[],actions[]}` model, the inline-button SENDER (`reply_markup.inline_keyboard`), `setMyCommands` slash commands — lands first in the foundation slice. Current `AgentConfig` (`models.py:54-59`) has only `enabled`/`schedule_cron`; the callback channel at `routes/telegram.py:49/136` handles only `approve:`/`reject:` via `_handle_plan_callback`; `send_telegram_message` (`dispatcher.py:47`) sends no `reply_markup`. **L0/L1 must land first.** Where a layer needs a primitive that isn't there, it adds the minimal version. Until then, the `Card`/state/sender symbols below are forward references to L0/L1.

## Safety invariants (all layers)

- **No autonomous calendar or money writes.** All writes — `create/move/update/delete_event`, any roster mutation — stay approval-gated via a `Card` tap. Calendar helpers hard-refuse unless `user_initiated=True`, set only inside an approval handler responding to a real button press (identical to the existing `create_event` gate, `google_calendar.py:87-103`).
- **Self-management proposes, never destroys.** Auto-park is reversible (undo button); **retire is never automatic** — it is only ever surfaced as a `fleet:retire:{id}` proposal requiring explicit human confirm.
- **Cooperative cancellation, never SIGKILL.** Long-runners poll a `cancel_requested` flag and a `GUIDANCE.md` inbox at milestone boundaries; live work is never force-killed.
- **Telegram stays fail-closed.** The allow-list check (`telegram.py:139`) precedes any callback handling; a non-allow-listed sender is dropped before dispatch.

## Build order

**L2 first** — highest daily value, smallest new surface, and it ships the `Card`+inline-keyboard sender that L3/L4 reuse (in the foundation slice, the Card channel ships in L1). **Then L3** — the long-runner, copying the builder's detached pattern. **Then L4** — fleet self-management, which depends on `AgentConfig.state` and the priority field being stable under real traffic.

## Cross-cutting reuse

- **Card + callback channel** — one inline-button `Card` model and one `callback_query` dispatcher; each layer adds a prefix (`op:`, `goal:`, `fleet:`) and a `_handle_*_callback` beside `_handle_plan_callback`.
- **`AgentConfig`** — `state` + DB schedules are the roster source of truth (L4 flips state; L2/L3 read it).
- **Scheduler** — all cadence is `CronTrigger`s registered via `register_*` in `main.py`, timezone `America/New_York`.
- **Builder detached pattern** — `start_new_session` spawn + `Job` row (pid/log) + worktree + `GUIDANCE.md`/`BLOCKED` reply loop + `recover_orphans`; L3 clones it wholesale.

---

## L2 — Proactive Daily Operator

### Components
1. **`operator.py`** (new) — the single **parent routine**. `async def run_phase(phase, day=None)`, `phase ∈ {morning, midday, eod}`. Morning = brief (`schedule_daily.generate_daily_brief`) + day-plan (`planner.generate_plan_with_agent`) + an **approval `Card`** of proposed calendar changes. Midday = re-read free/busy, surface slipped focus block / unstarted high-priority tasks. EOD = recap (completed tasks, approved-vs-skipped items, tomorrow preview). Sequencing lives here, not in the scheduler.
2. **`freebusy.py`** (new) — `find_gaps(day, min_minutes=120, work_start, work_end)` calls a new `google_calendar.freebusy()`, subtracts busy intervals (tz `America/New_York` via `zoneinfo`), returns the first qualifying gap. Replaces the hardcoded `09:00–11:00` block at `planner.py:74-79`.
3. **Calendar write helpers** — add `http_patch_json`/`http_delete` to `integrations/base.py` (mirror `http_post_json` at `base.py:87`) and `move_event`/`update_event`/`delete_event`/`freebusy` to `google_calendar.py`, each gated `user_initiated: bool = False` exactly like `create_event`.
4. **`Card` model + inline sender** (`dispatch/cards.py`) — the `Card` dataclass + `send_card(chat_id, card)` posting `reply_markup.inline_keyboard` of `{text, callback_data}`. Ships in the foundation slice (L1).

### Data flow
`scheduler` cron → `operator.run_phase(phase)` → reads (calendar/freebusy/tasks/brief) → `planner` stages `PlanItem` rows (`status=proposed`; never writes) → `operator` builds a `Card` → `send_card` → Telegram → user tap → `callback_query` (`telegram.py:136`) → `_handle_operator_callback` → `approve_item`/`reject_item` (`planner.py:361/417`), the sole write path.

### Approval-card UX
One `Card` per phase. Calendar changes batched: headline `"3 calendar changes proposed"`, one line per item, actions `[Approve all]` `[Edit]` `[Skip]`. `callback_data`: `op:approveall:{day}:{phase}`, `op:skip:{day}`, `op:edit:{item_id}` (Edit replies with per-item `approve:{id}`/`reject:{id}` buttons — reuses the existing planner verbs). Telegram caps `callback_data` at 64 bytes — keep keys short. After tap, edit the message text in place to a confirmation. Move/update/delete proposals carry `{op, event_id, …}` in `PlanItem.payload_json`; `approve_item` dispatches on it.

### Safety gating
No new autonomous write path. `move/update/delete_event` hard-refuse unless `user_initiated=True`, set **only** inside `approve_item` in response to a real tap. Operator routines call `generate_plan_*` (staging only) and `send_card`; they never touch `create_event`/patch/delete.

### Files
- **Add**: `operator.py`, `freebusy.py`, `dispatch/cards.py`.
- **Modify**: `integrations/base.py` (+`http_patch_json`,`http_delete`); `integrations/google_calendar.py` (+`move/update/delete_event`,`freebusy`, all `user_initiated`-gated); `planner.py` (`approve_item` branches on `payload["op"] ∈ {create,move,update,delete}`; `_build_proposals` calls `freebusy.find_gaps`); `scheduler.py` (`register_operator()`: 3 `CronTrigger`s `timezone=ZoneInfo("America/New_York")` at 07:00/13:00/18:00 ET — mirror `register_planner`); `routes/telegram.py` (extend callback dispatch with `op:` → `_handle_operator_callback`); `main.py` (`register_operator()`); `dispatcher.py` (`send_telegram_message` accepts optional `reply_markup`, or new `send_card`).

### Tests
- `find_gaps`: empty calendar → full window; back-to-back → first ≥120min gap; DST boundary tz-correct.
- `move/update/delete_event` refuse when `user_initiated=False`; succeed with mocked `http_patch_json`/`http_delete`.
- `approve_item` dispatches each `op` to the right helper with `user_initiated=True`; stays `proposed` if disconnected (extends the planner retry invariant).
- `run_phase`: morning stages plan + sends one `Card`; midday/eod send recaps; no write occurs.
- callback: `op:approveall` approves all proposed items for the day; `op:skip` rejects; non-allow-listed sender dropped.
- `send_card` emits well-formed `inline_keyboard`; `callback_data` ≤ 64 bytes.

---

## L3 — The Goal Long-Runner

### Data model (`models.py`)
Two new tables plus reused `Job` fields. A goal is the durable unit; milestones are its plan; the live `Job` (`kind="goal"`) carries the detached pid/log exactly like the builder.

```python
class Goal(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="job.id", index=True)   # the kind="goal" Job
    text: str                                               # raw "goal:" prompt
    status: str = Field(default="planning", index=True)     # planning|running|checkin|paused|done|aborted|failed
    cancel_requested: bool = Field(default=False)           # polled flag (NOT a kill)
    cursor: int = Field(default=0)                          # index of current milestone
    repo_path: str | None = None                            # worktree base (reuse builder REPO)
    chat_id: int | None = None
    created_at / updated_at: datetime

class Milestone(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    goal_id: int = Field(foreign_key="goal.id", index=True)
    seq: int = Field(index=True)
    title: str
    status: str = Field(default="pending")                  # pending|active|done|skipped|blocked
    result: str | None = None                               # cleaned summary for the check-in Card
    started_at / completed_at: datetime | None
```
Reuse `Job.worker_pid/log_path/qa_verdict/worker_branch` unchanged. `cancel_requested` + a `GUIDANCE.md` inbox (the builder's exact mechanism) are the only steering surface — no blocking kill.

### Driver loop (`scripts/goal_run.py`, mirrors the builder-run contract)
Detached `start_new_session` process spawned by `dispatch/goal.py::start_goal` (copy `builder._spawn`). One outer loop:
1. No milestones → run a CEO decompose (reuse `dispatch/mission.py::_parse_subtasks` parsing + degrade-to-single fallback), persist `Milestone` rows, set `status=running`.
2. For each `pending`/`active` milestone in `seq` order: re-read `Goal` from DB; **poll `cancel_requested`** and drain `GUIDANCE.md` first; mark `active`; execute one milestone as a bounded headless run in the worktree (reuse builder prompt scaffold + `clean_agent_output`); store cleaned `result`; mark `done`; advance `cursor`.
3. After each milestone (or every `GOAL_CHECKIN_EVERY=1` / `GOAL_CHECKIN_SECONDS=1800`, whichever first) → emit a **check-in `Card`**, set `status=checkin`, and either auto-continue (default after `GOAL_CHECKIN_GRACE` if unanswered) or block on a button.
4. Loop until milestones exhausted → `status=done`, post final `Card`, `cleanup_worktree`.

### Check-in cadence & Card
Reuse the L1 `Card` + inline sender. Per check-in: headline = goal, lines = last milestone result + `cursor/total`, actions `[Continue]`/`[Steer]`/`[Abort]` with `callback_data` `goal:cont:{id}` / `goal:steer:{id}` / `goal:abort:{id}`.

### Steer/abort (`routes/telegram.py`)
Add `_handle_goal_callback` beside `_handle_plan_callback`; dispatch from the `callback_query` branch. `cont` clears checkin→running; `abort` sets `cancel_requested=True`; `steer` and any free-text reply to a goal `Card` route through `dispatch/goal.py::handle_goal_reply` (clone of `builder.handle_builder_reply`), which appends to `GUIDANCE.md` and flips status back to running. The driver acts on its next poll — cooperative, never SIGKILL.

### Durability / resume
All state in DB + worktree files; the loop is idempotent on `cursor`/milestone `status`. Extend `dispatch/worker.recover_orphans` (or a `recover_goals()` in lifespan) to find dead-pid `kind="goal"` Jobs and re-`_spawn(resume=True)`; a live pid is left alone (builder's orphan rule). Resume re-reads `cursor`, continues from the first non-`done` milestone — completed work is never redone.

### Files
- **Add**: `models.py` (Goal, Milestone), `dispatch/goal.py`, `scripts/goal_run.py`, `dispatch/goal_cards.py`.
- **Modify**: `routes/telegram.py` (`goal:` regex near `_BUILD_RE`, callback dispatch), lifespan (`recover_goals`), `_fleet_status_text` (show goal jobs).

### Tests
- `test_goal_decompose`: CEO output → milestone rows; degrade-to-single on bad JSON.
- `test_goal_driver_advances`: cursor/milestone transitions on success/block.
- `test_goal_cancel_polled`: `cancel_requested` stops at next boundary, no kill.
- `test_goal_guidance_inbox`: reply appends `GUIDANCE.md`, status→running.
- `test_goal_resume`: dead pid → re-spawn resume; done milestones not rerun.
- `test_goal_checkin_card`: 3 actions + correct `callback_data`.
- `test_goal_callback_dispatch`: cont/steer/abort routed; non-allow-listed sender ignored.

---

## L4 — Fleet Self-Management

The mesh manages its own queue and roster: prioritizes work, watches fleet health, parks idle agents — every destructive change human-gated. Builds on L0/L1 (`AgentConfig.state`, `Card`, inline sender, `callback_query` dispatch).

### Components
- **`fleet/priority.py`** — derives an integer `priority` for a Job at enqueue.
- **`fleet/health.py`** — pure check functions over `Job`/`AgentRun`/`AgentConfig`; returns `HealthFinding[]`.
- **`fleet/cards.py`** — the weekly health `Card` and the auto-park notify+undo `Card`.
- **`fleet/actions.py`** — `park_agent`/`reactivate_agent` (flip `AgentConfig.state`, toggle schedule via `scheduler_service`), idempotent.
- Scheduler jobs: `fleet-health` (weekly, Mon 8am ET) + daily idle-park sweep.

### Priority model (worker drains by priority, not FIFO)
Add `Job.priority: int = Field(default=50, index=True)`. Bands: user Telegram/`/jobs` = **100**; thread follow-ups = **90**; auto-park/health internal = **60**; scheduled cron = **50**; backfill/sweep = **10**. `priority()` maps `kind` + source. Change `dispatch/worker.py::claim_next` to `order_by(Job.priority.desc(), Job.created_at)` — highest band first, FIFO within. Concurrency cap unchanged. Reality check: trader+inbox crons (91% of traffic) stay at 50, so a single user query jumps the cron flood without starving it.

### Health checks + thresholds (`fleet/health.py`)
- **Idle**: scheduled agent with last run > **7 days** → suggest park. Trader (`*/30`) and inbox (`*/2h`) never trip this.
- **High failure rate**: ≥ **5** runs in 7 days AND `failed/total ≥ 0.5` → flag.
- **Runaway/orphaned**: Job `RUNNING` with `started_at` older than **2h** (telegram_dispatch) / **6h** (builder) → flag for `recover_orphans`/cancel.
Each is a pure function returning findings with severity; thresholds are module constants.

### Auto-park flow with undo
Daily sweep calls `health.idle_agents()`. Per agent: `actions.park_agent(id)` flips `state→parked`, calls `scheduler_service.remove_schedule(id)`, persists; sends a `Card` "Parked {id} — idle 7d" with action `fleet:unpark:{id}`. The `callback_query` dispatch routes `fleet:*` to a new `_handle_fleet_callback` (mirrors `_handle_plan_callback`, same allow-list) → `reactivate_agent` flips `state→active`, `set_schedule` to default cron. **Retire is never automatic** — the health `Card` surfaces a `fleet:retire:{id}` button that only proposes; retire requires explicit human confirm.

### Files
- **Add**: `fleet/__init__.py`, `fleet/priority.py`, `fleet/health.py`, `fleet/cards.py`, `fleet/actions.py`, `routes/fleet.py` (GET `/fleet/health`).
- **Modify**: `models.py` (`Job.priority`); `dispatch/worker.py` (enqueue sets priority, `claim_next` ordering); `routes/telegram.py` (`_handle_fleet_callback` + `fleet:` route); `scheduler.py` (`register_fleet_health` weekly + daily idle sweep); `routes/jobs.py` (`create_job` sets priority=100).

### Tests
- `test_fleet_priority.py`: band mapping per kind/source; user(100) > scheduled(50) > sweep(10).
- `test_worker_priority.py`: `claim_next` returns high-priority before older low-priority; FIFO tiebreak; cap respected.
- `test_fleet_health.py`: idle-7d trips (trader/inbox don't); failure-rate ≥0.5 over ≥5; orphan-age thresholds.
- `test_fleet_actions.py`: park flips state + removes schedule, idempotent; reactivate restores default cron.
- `test_fleet_cards.py`: weekly `Card` has findings as lines + retire-as-proposal action; park `Card` carries `fleet:unpark:{id}`.
- `test_fleet_callback.py`: `fleet:unpark` reactivates; `fleet:retire` only proposes (no state change); non-allow-listed sender ignored.
