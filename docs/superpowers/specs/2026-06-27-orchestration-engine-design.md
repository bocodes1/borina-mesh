# Borina Mesh — Orchestration Engine Design

**Date:** 2026-06-27
**Status:** Approved design — pending implementation plan
**Depends on:** `2026-06-18-autonomy-layer-L2-L3-L4-design.md` (the L2/L3/L4 autonomy layer — Cards, cooperative cancel, the goal long-runner) and assumes the `2026-06-27-os-efficiency-overhaul-design.md` efficiency overhaul has landed (recurring Opus → 0, the roster gate applied uniformly).

Today the mesh has **two** unrelated orchestration primitives that share nothing but a CEO decompose call. `mission` is a flat fan-out: the CEO splits a prompt into ≤4 independent read-only subtasks, `asyncio.gather`s them, and synthesizes one report (`dispatch/mission.py:75-120`). `goal` is a linear runner: decompose into ordered milestones, then a cursor walks them one at a time with check-in Cards (`dispatch/goal.py:134-209`). Neither expresses the obvious middle ground — *some* sub-tasks depend on others, so the work is a **graph**, not a line and not a star. This spec unifies both into ONE DAG-based orchestration engine: the CEO decomposes work into a directed acyclic graph of sub-agent tasks with dependency edges; a driver runs them parallel where independent and sequential where dependent; a `verify` node gates the synthesized result; and the live DAG is observable on the Network tab. `mission` and `goal` survive as two **modes** of the same engine (ephemeral vs. durable), not two codebases.

## Safety invariants (must not weaken)

- **No autonomous writes.** A write node NEVER self-executes. When a write node becomes ready it flips to `awaiting_approval` and emits an approval `Card`; its branch pauses. The write happens only on the user's tap, through the exact existing `user_initiated=True` gate (`integrations/google_calendar.py:89-105`, hard-refuse at `:101-105`). The engine has no path to approve itself. This preserves the autonomy-layer invariant verbatim (`2026-06-18-autonomy-layer-L2-L3-L4-design.md` §Safety invariants).
- **Cooperative cancellation, never SIGKILL.** Steering is the polled `cancel_requested` flag plus a GUIDANCE inbox drained at **node boundaries** — the goal runner's exact mechanism (`dispatch/goal.py:153`, `:112-130`). Live work is never force-killed; the driver acts on its next poll.
- **Telegram stays fail-closed.** The secret-token check (`routes/telegram.py:30-33`, `:572`) and the allow-list (`routes/telegram.py:586`, `:601`) precede any callback handling. A write-node approval tap is a `callback_query` and is dropped for a non-allow-listed sender exactly like every other Card tap.
- **Read nodes stay read-only.** A `read`-kind node may only target the read-only intel roster `MISSION_AGENTS` (`dispatch/mission.py:19`). The decompose validator rejects a `read` node bound to a write-capable agent. A regression test mirrors the planner's "no autonomous write" guard (below, Tests).

## Build order

**1. Data model + driver first** — the `Run`/`Task`/`TaskEdge` schema and the ready-set driver, with the per-node runner **injected** (the goal runner's testability trick, `dispatch/goal.py:134`) so the whole engine is unit-testable before any agent spawns. **2. Decompose contract + degradation** — the CEO emits a DAG JSON, validated and degraded to today's behavior on garbage. **3. Write nodes + verify gate** — the two safety-sensitive slices, each landing with its regression test. **4. Observability** — `routes/runs.py` and the Network run-view, last because it only reads state the driver already persists. **5. Fold + migrate** — point the `mission:`/`goal:` entry points at the engine; migrate existing rows.

## Cross-cutting reuse

- **Cards + callback channel** — the inline-button `Card`/`Action` model with the 64-byte `callback_data` cap (`dispatch/cards.py:18-37`, `send_card` at `:57`) and the prefix dispatch in `routes/telegram.py:265-293`. The engine adds a `run:` prefix for write-node approvals and reuses the existing `goal:` check-in verbs.
- **Injected per-node runner** — the goal driver already takes `run: Callable[[str], Awaitable[str]]` (`dispatch/goal.py:134`, default at `:243`); the DAG driver keeps the same seam so tests pass a stub instead of spawning agents.
- **tmux pool + priority bands** — nodes execute via `agents.runner_v2.run_agent_task` (`agents/runner_v2.py:172`), one persistent tmux session per agent, bounded by the pane pool (`agents/runner_v2.py:8`). Concurrency is capped by that pool and ordered by the existing bands (`fleet/priority.py:3-21`).
- **Detached Job + recover-on-boot** — a run owns a `Job(kind="run")` carrying pid/log (`models.py:31-37`) exactly like `kind="goal"`; `recover_runs()` on boot mirrors `recover_goals()` (`dispatch/goal.py:290-300`, registered at `main.py:62-67`).
- **CEO prompts** — `DECOMPOSE_PROMPT`/`SYNTH_PROMPT` (`dispatch/mission.py:23`, `:31`) and the newline-collapse JSON repair (`dispatch/mission.py:59`) are kept where still useful.

---

## Data model

One run container generalizes `Goal`; one node table generalizes `Milestone`; one edge table is new. The live `Job(kind="run")` carries the detached pid/log like the builder and the goal runner.

```python
class Run(SQLModel, table=True):
    """A unit of orchestrated work — a DAG of Tasks. Generalizes the old Goal."""
    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: Optional[int] = Field(default=None, foreign_key="job.id", index=True)
    text: str                                               # raw "mission:"/"goal:" prompt
    mode: str = Field(default="mission", index=True)        # mission | goal
    status: str = Field(default="planning", index=True)     # planning|running|checkin|paused|done|aborted|failed
    cancel_requested: bool = Field(default=False)           # polled flag — NOT a kill
    chat_id: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class Task(SQLModel, table=True):
    """One node of a Run's DAG. Generalizes the old Milestone."""
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="run.id", index=True)
    key: str = Field(index=True)                            # stable node key from the decompose ("research")
    agent: str                                              # short agent id (researcher, trader, planner, ceo…)
    kind: str = Field(default="read", index=True)           # read | write | verify | synthesize
    prompt: str
    status: str = Field(default="pending", index=True)
    # pending | ready | active | done | skipped | blocked | awaiting_approval | failed
    result: Optional[str] = None                            # cleaned summary, fed downstream + to Cards
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

class TaskEdge(SQLModel, table=True):
    """A dependency edge: dst depends on src (src must be done before dst is ready)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="run.id", index=True)
    src: str = Field(index=True)                            # Task.key of the upstream node
    dst: str = Field(index=True)                            # Task.key of the downstream node
```

**Field notes.** `Run.mode` is the only behavioral switch: **mission** = ephemeral, runs to completion silently with progress pings, no resume cursor needed beyond crash-recovery; **goal** = durable, emits a check-in `Card` at phase boundaries, resumable across restarts. `Task.status` is the richer set the decisions call for — note `awaiting_approval` (write-node pause) and `blocked` (a dependent of a skipped/failed node) are new versus the old `Milestone` set (`models.py:120`). `Task.key` replaces `Milestone.seq` as the identity used by edges, so ordering is now expressed by `TaskEdge` rather than an integer cursor.

**Migration from Goal/Milestone.** `init_db`'s `create_all` adds the three tables (the existing `OutreachReply`/`PostingApplication` additions used the same no-ALTER pattern). Existing rows migrate one-shot in the lifespan boot path beside `recover_goals` (`main.py:62-67`): each `Goal` → a `Run(mode="goal", text, status, cancel_requested, chat_id, job_id)`; each `Milestone(seq=i)` → a `Task(kind="read", key=f"m{seq}", agent="researcher", status, result)` plus a chain edge `TaskEdge(src=f"m{i}", dst=f"m{i+1}")` reproducing the old linear order. The legacy `Goal`/`Milestone` tables are left in place (read-only) for one release, then dropped in a follow-up — no destructive migration in this slice.

---

## The DAG driver

Replaces the goal runner's linear cursor walk (`dispatch/goal.py:134-209`) with a ready-set loop. The per-node runner stays **injected** so the driver is unit-testable without spawning agents.

**Ready-set algorithm.** A node is **ready** when its status is `pending` and every upstream `TaskEdge.src` node is `done`. (A node with no incoming edges is ready immediately — these are the roots, equivalent to mission's parallel fan-out.) Each tick:

1. Re-read the `Run` from the DB; poll `cancel_requested` and drain the GUIDANCE inbox first (cooperative — `dispatch/goal.py:153`, `:112-130`).
2. Compute `ready = {t for t in tasks if t.status=="pending" and all(dep.status=="done" for dep in upstream(t))}`.
3. **Write nodes never run here.** Any ready node with `kind=="write"` flips to `awaiting_approval`, emits an approval Card, and is removed from the batch (see Write nodes). The driver does not block on it — other branches keep moving.
4. Run the remaining ready nodes **concurrently** via `asyncio.gather` (mission's exact fan-out shape, `dispatch/mission.py:103`), each through the injected runner; concurrency is bounded by the tmux pane pool and ordered by the priority bands (`fleet/priority.py`). Mark each `active` → `done`/`failed`, store the cleaned `result`.
5. **Persist after each node** (one `session_scope` write per node, like `dispatch/goal.py:187-200`), then recompute the ready set.
6. A node that `failed` marks its transitive dependents `blocked` (they can never become ready); independent branches continue. Loop until no node is `pending`/`ready`/`active`.

**Parallel vs. sequential falls out for free.** Independent branches share no edge, so they enter the ready set together and gather concurrently. Dependent branches serialize because the downstream node is not ready until its upstream is `done`. A diamond (`A → {B, C} → D`) runs `A`, then `B`+`C` in parallel, then `D` — no special-casing.

**Upstream results as context.** Before running node `N`, the driver gathers `result` from every `TaskEdge.src` of `N` and prepends them to `N.prompt` as a context block (the same shape mission feeds synthesis, `dispatch/mission.py:108-113`, capped per node like `_RESULT_CAP`). A root node gets no context; `synthesize` gets every leaf's result.

**Resume.** All state lives in `Task`/`TaskEdge` — there is no separate cursor to keep in sync. On boot, `recover_runs()` (mirroring `recover_goals`, `dispatch/goal.py:290-300`) finds runs left `running`/`checkin`/`planning` with a dead-pid `Job`; for **goal** mode it marks them `paused` so a Continue tap resumes; for **mission** mode it re-spawns the driver, which simply **recomputes the ready set** from persisted statuses — `done` nodes are never rerun, in-flight `active` nodes are reset to `pending` and rerun (idempotent, since a node's output is its `result`).

**Cooperative steering.** `cancel_requested` and the GUIDANCE inbox are drained only at node boundaries (between gather batches), never mid-node. `abort` sets the flag → next tick the run goes `aborted` (`dispatch/goal.py:153-158`). Steering guidance appends to the prompt of the next not-yet-`active` ready node and flips status back to `running` (`dispatch/goal.py:112-130`). No blocking kill, ever.

**Mode-specific surfacing.** **goal** mode emits a check-in `Card` (`[Continue]`/`[Steer]`/`[Abort]`, `dispatch/goal.py:212-229`) at phase boundaries — defined as: after the last read/write node completes (pre-synthesis), and at finalize. **mission** mode runs silently and sends only a progress ping (`dispatch/mission.py:90-97`'s `progress` callback) — N nodes dispatched, then the final synthesized report.

---

## Write nodes (gated autonomy slice)

This is the engine's one new autonomy capability, and it is gated identically to every existing write in the mesh.

A `write`-kind node represents a real side-effecting action (a calendar create/move, an outreach send) routed to a write-capable agent. **It is never executed by the driver.** When such a node becomes ready (all upstream `done`), the driver:

1. Sets `Task.status = "awaiting_approval"` and stops advancing **that branch only** — independent branches keep running.
2. Emits an approval `Card`: headline = the node's intent, lines = the upstream context that justifies it, actions `[Approve]` / `[Reject]` with `callback_data` `run:approve:{task_id}` / `run:reject:{task_id}` (≤64 bytes, `dispatch/cards.py:18-28`).
3. On **Approve** tap → `_handle_run_callback` (new, beside `_handle_goal_callback` at `routes/telegram.py:296`) executes the write **with `user_initiated=True`** — the exact gate at `integrations/google_calendar.py:101-105`, set only inside the approval handler in response to a real allow-listed button press. Node → `done`; its dependents re-enter the ready set and unblock.
4. On **Reject** tap → node → `skipped`; its transitive dependents → `blocked`/`skipped` (they depended on an action that never happened). The run continues with whatever branches remain.

**The engine cannot self-approve.** There is no code path from the driver to `user_initiated=True`; the only setter lives in the `callback_query` handler, behind the fail-closed allow-list (`routes/telegram.py:586`, `:601`). A write node left untapped sits in `awaiting_approval` forever (or until the run is aborted) — it can never time out into execution. This is the same propose-then-tap model as the planner (`routes/telegram.py:49-79`), the operator (`routes/telegram.py:350-406`), and the applier (`routes/telegram.py:478-537`).

**Regression test (required).** A test mirrors the planner's "no autonomous write" guard: drive a DAG containing a `write` node to the point it becomes ready, assert the write helper is **never called** (mock asserts zero calls) and the node sits in `awaiting_approval`; then simulate the approval tap and assert the helper is called exactly once **with `user_initiated=True`**.

---

## Verify gate

A single independent `verify`-kind node sits **after** the `synthesize` node (edge `synthesize → verify`). It is the engine's quality gate, bounded to respect the credit budget.

The verify node runs the CEO as critic (pinned, per the decompose contract below) with a prompt that takes the synthesized result plus every leaf node's `result` and returns a structured verdict `{ "pass": bool, "reasons": [str] }` (parsed with the same tolerant JSON extraction as `_parse_subtasks`, `dispatch/mission.py:49-72`). 

- **pass** → finalize: `Run.status = "done"`, post the final report/Card.
- **fail** → **exactly ONE** bounded retry: re-run the `synthesize` node once with the critic's `reasons` appended to its prompt, then **finalize regardless** of the second verdict. There is no loop — bounded to 1 to cap the credit cost (a fail-twice run still finalizes with the best synthesis and surfaces the critic's caveat). On a verify-node parse failure, degrade to `pass` (never block a finished run on a flaky critic).

The retry mutates only the `synthesize` node (reset to `pending`, rerun, re-feed `verify` once); the read/write nodes' results are reused, not recomputed — they already passed their own gates.

---

## Decompose contract

The CEO emits the DAG as a single JSON object (no prose, no code fences — same discipline as `dispatch/mission.py:26-29`):

```json
{
  "nodes": [
    {"key": "research",  "agent": "researcher", "kind": "read",      "prompt": "...", "depends_on": []},
    {"key": "prices",    "agent": "trader",     "kind": "read",      "prompt": "...", "depends_on": []},
    {"key": "synth",     "agent": "ceo",        "kind": "synthesize","prompt": "...", "depends_on": ["research","prices"]},
    {"key": "verify",    "agent": "ceo",        "kind": "verify",    "prompt": "...", "depends_on": ["synth"]}
  ]
}
```

**Validation (reject the whole DAG on any failure → degrade):**
1. **Topological sort** over `depends_on` — **reject cycles** (Kahn's algorithm: if the ready frontier empties before all nodes are placed, there is a cycle).
2. **Roster** — every `read` node's `agent` ∈ `MISSION_AGENTS` (`dispatch/mission.py:19`); `write` nodes' agents ∈ the write-capable allow-list; `verify`/`synthesize` pinned to `ceo`. An out-of-roster agent rejects the DAG.
3. **Node cap** — `len(nodes) ≤ 8` (cost cap). Over-cap rejects.
4. **Write flagging** — any node whose `kind=="write"` is recorded as gated (it can never be a root that auto-runs; it always pauses). Every `depends_on` key must reference a declared node.
5. **Terminal gate** — exactly one `synthesize` node and one `verify` node, with `verify` depending on `synthesize`; so "the synthesize node" is always unambiguous (the verify retry re-runs that one node). The mission fallback synthesizes; the goal single-node fallback skips the synthesize/verify pair.

**Graceful degradation** (never raise into a Telegram reply — same posture as `dispatch/mission.py:78-79`): on parse failure or any validation reject, fall back to **today's behavior** —
- **mission** mode → the flat fan-out: reuse `_parse_subtasks` (`dispatch/mission.py:49`) to build ≤4 independent `read` nodes + one `synthesize`, or a single `researcher` node if even that fails (`dispatch/mission.py:87-89`), and the deterministic section-join report if synthesis is empty (`dispatch/mission.py:120`).
- **goal** mode → a single `read` node over the raw goal text (`dispatch/goal.py:48-57`'s degrade-to-single).

So a broken CEO output degrades to exactly what ships today; the DAG is strictly additive.

---

## Observability

**`routes/runs.py`** (new — replaces the dead `routes/threads.py` stub, `routes/threads.py:1-5`, swapped in at `main.py:154`). Endpoints:
- `GET /api/runs` → recent runs (id, mode, status, node counts).
- `GET /api/runs/{id}` → the full DAG: `{run, nodes:[{key,agent,kind,status,result?}], edges:[{src,dst}]}` with live statuses, read straight from `Task`/`TaskEdge`.

**Network graph — a "run" view.** The graph today draws only hub↔agent edges (`apps/web/components/network-graph.tsx:43`, `HUB="mesh"` at `:11`) with particles travelling hub→agent (`:134-139`). Add a **run view** that, given a run id, renders the actual task DAG: nodes = `Task`s (colored by `status`), edges = `TaskEdge`s as **real agent→agent edges**. An edge **pulses** when its `dst` node activates — the first time this tab shows genuine inter-agent work rather than a star of pings. It reuses the existing activity pulse mechanism (`subscribeToActivity`, `network-graph.tsx:50`; `ActivityEvent` in `apps/web/lib/activity.ts`), keyed on node `key` instead of `agent_id`. The default "fleet" view (hub↔agent) is unchanged; the run view is a toggle on `/network` (`apps/web/app/network/page.tsx`).

**Jobs tab — parent/child.** A run surfaces as a parent row (its `Job(kind="run")`) with its `Task` nodes as children (status + agent + result preview), reusing the jobs list shape (`apps/web/lib/api.ts` `listJobs`/`getJobRuns`). The new `getRun(id)` client call feeds both the run-view graph and the Jobs expansion.

---

## Entry points & migration

**Commands (unchanged surface).** Reuse the two existing triggers:
- `mission: …` → `mode=mission`. Today it routes via intent (`dispatch/intent.py:124`) → `dispatcher.py:161` → `run_mission`. Repoint that call at the engine with `mode="mission"`.
- `goal: …` → `mode=goal`. Today `routes/telegram.py:651-664` calls `goal_mod.create_goal` + `launch_goal`. Repoint at the engine with `mode="goal"`; keep the same "I'll check in after each phase / reply to steer / tap Abort" ack and the `goal:` thread anchor (`routes/telegram.py:662`).

**Fold the old modules in.** `dispatch/mission.py` and `dispatch/goal.py` collapse into the engine (a new `dispatch/orchestrator/` package: `dag.py` driver + `decompose.py` contract). Keep `DECOMPOSE_PROMPT`/`SYNTH_PROMPT` (`dispatch/mission.py:23`, `:31`), the JSON repair (`:59`), `MISSION_AGENTS` (`:19`), the injected-runner seam and `recover_goals`/check-in Card logic (`dispatch/goal.py`). The old `run_mission`/`advance_goal` functions become thin shims (or the degrade paths) so nothing else that imports them breaks during the transition.

**Row migration.** As above (Data model): existing `Goal`/`Milestone` rows migrate to `Run`/`Task`/`TaskEdge` one-shot on boot beside `recover_goals` (`main.py:62-67`); legacy tables kept read-only for a release. `recover_goals` is renamed/extended to `recover_runs` and registered in the same lifespan slot.

---

## Files

**Add:**
- `dispatch/orchestrator/__init__.py`
- `dispatch/orchestrator/dag.py` — the ready-set driver (injected runner, persist-per-node, resume, cooperative steer, write-node pause, verify gate).
- `dispatch/orchestrator/decompose.py` — DAG JSON parse + topo-sort/roster/cap validation + degradation to mission/goal fallbacks.
- `routes/runs.py` — `GET /api/runs`, `GET /api/runs/{id}` (replaces the `routes/threads.py` stub).
- `apps/web/lib` — a `getRun(id)` / `listRuns()` client in `apps/web/lib/api.ts` + a `Run`/`RunNode`/`RunEdge` type in `apps/web/lib/types.ts`.

**Modify:**
- `models.py` — add `Run`, `Task`, `TaskEdge`; leave legacy `Goal`/`Milestone` in place for migration.
- `dispatch/mission.py` — fold `run_mission` into the engine; keep prompts + `_parse_subtasks` as the mission degrade path.
- `dispatch/goal.py` — fold `advance_goal` into the DAG driver; keep check-in Card + GUIDANCE/`cancel_requested` steering; rename `recover_goals` → `recover_runs` (+ row migration).
- `routes/telegram.py` — add `_handle_run_callback` (write-node `run:approve`/`run:reject`) to the prefix dispatch (`:265-293`); repoint the `goal:`/`mission:` entry points (`:651-664`, via `dispatcher.py:161`) at the engine.
- `main.py` — `include_router(runs_routes.router)` in place of the threads stub (`:154`); `recover_runs()` in the lifespan slot (`:62-67`).
- `dispatch/dispatcher.py` — `mission` task-type (`:161-164`) calls the engine.
- `scheduler.py` — only if a run needs a recurring sweep (e.g. surface long-stalled `awaiting_approval` runs); otherwise untouched.
- `apps/web/components/network-graph.tsx` — add the run view (task DAG, agent→agent edges, per-node pulse) alongside the fleet view; `apps/web/app/network/page.tsx` — a view toggle.

---

## Tests

- **Ready-set computation** — given nodes + edges and a status map, `ready()` returns exactly the `pending` nodes whose upstreams are all `done`; roots are ready immediately.
- **Diamond DAG** — `A → {B,C} → D`: `A` runs first, `B`+`C` gather concurrently (assert both started before either's downstream), `D` runs last after both join. Injected runner records call order.
- **Cycle rejection** — a decompose with `A→B→A` is rejected by the topo-sort; the engine degrades to the mission/goal fallback rather than raising.
- **Resume from partial state** — a DAG with some nodes `done`, one `active`, rest `pending`; `recover_runs` + restart reruns only the non-`done` nodes, never the `done` ones (assert the runner is not called for completed keys).
- **Cancel at a node boundary** — `cancel_requested=True` set mid-run stops at the next batch boundary with the in-flight node finishing or resetting; status → `aborted`; no kill signal sent (mirrors `test_goal_cancel_polled`).
- **Write-node gating** — a `write` node that becomes ready flips to `awaiting_approval` and the write helper is **never called**; on the approve tap the helper is called exactly once with `user_initiated=True`; on reject the node is `skipped` and its dependents become `blocked`/`skipped`.
- **No-autonomous-write regression** — drive a full DAG containing a write node end-to-end with **no** approval tap; assert the run finishes (other branches) with the write helper call count == 0 and the node still `awaiting_approval` (the engine never self-approves).
- **Verify fail → one retry → finalize** — a critic returning `{pass:false}` triggers exactly one re-synthesis (assert `synthesize` runner called twice, `verify` called twice), then the run finalizes regardless of the second verdict; a critic parse error degrades to `pass`.
- **Decompose parse** — valid CEO JSON → the expected `Task`/`TaskEdge` rows (keys, kinds, edges); garbage/empty → graceful degrade (mission → ≤4 read nodes + synthesize, or single researcher; goal → single read node).
- **Roster + cap** — a `read` node bound to a write-capable agent is rejected; a `>8`-node DAG is rejected; both degrade.
- **Migration** — a legacy `Goal` + N `Milestone` rows migrate to one `Run(mode="goal")` + N `Task`s chained by `TaskEdge`, preserving order and `done` statuses.

---

## Future / non-goals (v2)

Explicitly **out of scope** for v1 (this slice is a **static DAG**: decompose once into a fixed graph; the only mid-run mutation is the single bounded verify retry):

- **Dynamic re-planning / node-spawning** — a node deciding at runtime to add downstream nodes, or the CEO re-decomposing mid-run based on partial results. v1 commits to the DAG emitted at decompose time.
- **Node-spawning loops** — recursive/iterative sub-graphs (a node that fans out to a variable number of children). The verify gate is deliberately bounded to one retry precisely to avoid loops.
- **Adversarial verify panels** — multiple critics / debate / best-of-N verification. v1 is a single critic, one retry.
- **Per-node model selection** — pinning specific nodes to Opus vs. Sonnet. v1 inherits whatever the tmux pool / `AGENT_MODELS` resolves per agent (and the efficiency overhaul keeps recurring Opus at 0); deliberate per-node model routing is a later optimization.
