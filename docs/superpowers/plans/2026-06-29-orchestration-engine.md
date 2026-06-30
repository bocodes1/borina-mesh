# Orchestration Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify the two orchestration primitives (`mission` flat fan-out, `goal` linear milestones) into one DAG engine: the CEO decomposes work into a directed acyclic graph of sub-agent tasks; a ready-set driver runs them parallel-where-independent / sequential-where-dependent; write nodes pause for approval; a verify node gates the result; the live DAG is observable.

**Architecture:** New `dispatch/orchestrator/` package (`dag.py` driver + `decompose.py` contract) backed by three new tables (`Run`/`Task`/`TaskEdge`). The per-node runner is **injected** (the goal runner's testability seam) so the whole engine unit-tests without spawning agents. `mission`/`goal` become two `mode`s of one engine; the old `run_mission`/`advance_goal` become the degrade paths. Build order: data model + driver → decompose → write-nodes + verify → observability → fold + migrate.

**Tech Stack:** Python 3.11, FastAPI, SQLModel/SQLite, APScheduler, pytest (hermetic via `apps/api/conftest.py`); agents via the `claude` CLI tmux pool (`runner_v2.run_agent_task`); Next.js/React web. Full design: `docs/superpowers/specs/2026-06-27-orchestration-engine-design.md` (read it — every task cites it).

## Global Constraints

- **No autonomous writes.** A `write` node NEVER self-executes. It flips to `awaiting_approval`, emits a Card, and the write happens ONLY in the Telegram approval callback with `user_initiated=True` (`integrations/google_calendar.py:101-105`). The engine has no path to `user_initiated=True`. A regression test (Task 4) mirrors the planner's no-autonomous-write guard.
- **Cooperative cancel only.** Steering = polled `cancel_requested` + GUIDANCE inbox drained at node boundaries (`dispatch/goal.py:153`, `:112-130`). Never a kill signal.
- **Telegram fail-closed.** Approval taps are `callback_query`s dropped for non-allow-listed senders before any handling (`routes/telegram.py` secret-token + allow-list), same as every Card.
- **Read nodes read-only.** A `read` node may only target `MISSION_AGENTS` (`dispatch/mission.py:19`). Decompose rejects a read node bound to a write-capable agent.
- **v1 is a STATIC DAG.** Decompose once; the only mid-run mutation is the single bounded verify retry. No dynamic re-planning, node-spawning, adversarial panels, or per-node model selection (spec §Future/non-goals).
- **Defaults chosen by the operator:** write-capable roster = **calendar only** in v1; goal-mode check-in cadence = **after the last read/write node (pre-synthesis) and at finalize**; legacy `Goal`/`Milestone` tables = **two-step** (keep read-only one release, drop later).
- **Backend tests hermetic:** `cd apps/api && source .venv/bin/activate && python -m pytest …`. Never touch the live `borina.db`/`.env`. Per-task commits on branch `feature/orchestration-engine`; no push/deploy until the whole plan is verified. **Pre-existing flake:** 3 UTC-boundary tests (`test_conversation_log.py`/`test_telegram_dispatch.py`) — ignore.

---

### Task 1: Data model — Run / Task / TaskEdge

**Files:**
- Modify: `apps/api/models.py` (add three tables; leave `Goal`/`Milestone` in place)
- Test: `apps/api/tests/test_orchestrator_models.py`

**Interfaces:**
- Produces: `Run(id, job_id, text, mode, status, cancel_requested, chat_id, created_at, updated_at)`, `Task(id, run_id, key, agent, kind, prompt, status, result, started_at, completed_at)`, `TaskEdge(id, run_id, src, dst)` — fields exactly per spec §Data model lines 35-67.

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/test_orchestrator_models.py
from sqlmodel import Session, select
from db import engine
from models import Run, Task, TaskEdge


def test_run_task_edge_roundtrip():
    with Session(engine) as s:
        run = Run(text="mission: scan market", mode="mission", status="running")
        s.add(run); s.commit(); s.refresh(run)
        s.add(Task(run_id=run.id, key="research", agent="researcher", kind="read", prompt="..."))
        s.add(Task(run_id=run.id, key="synth", agent="ceo", kind="synthesize", prompt="..."))
        s.add(TaskEdge(run_id=run.id, src="research", dst="synth"))
        s.commit()
        tasks = s.exec(select(Task).where(Task.run_id == run.id)).all()
        edges = s.exec(select(TaskEdge).where(TaskEdge.run_id == run.id)).all()
        assert {t.key for t in tasks} == {"research", "synth"}
        assert (edges[0].src, edges[0].dst) == ("research", "synth")
        assert tasks[0].status == "pending"  # default
```

- [ ] **Step 2: Run test → fails** (`ImportError: cannot import name 'Run'`). Run: `cd apps/api && source .venv/bin/activate && python -m pytest tests/test_orchestrator_models.py -v`

- [ ] **Step 3: Add the tables** to `apps/api/models.py` (copy the three classes verbatim from spec §Data model lines 35-67; ensure `from datetime import datetime` and `Optional` are already imported in that file — they are, used by `Goal`). `init_db`/`create_all` picks them up with no migration (same no-ALTER pattern as the existing `OutreachReply` table).

- [ ] **Step 4: Run test → passes.**

- [ ] **Step 5: Commit**

```bash
git add apps/api/models.py apps/api/tests/test_orchestrator_models.py
git commit -m "feat(orchestrator): Run/Task/TaskEdge data model"
```

---

### Task 2: Ready-set + DAG driver core

**Files:**
- Create: `apps/api/dispatch/orchestrator/__init__.py`, `apps/api/dispatch/orchestrator/dag.py`
- Test: `apps/api/tests/test_dag_driver.py`

**Interfaces:**
- Produces: `ready(tasks: list[Task], edges: list[TaskEdge]) -> list[Task]` (pure: pending tasks whose every upstream `src` is `done`; roots ready immediately); `async def drive_run(run_id: int, run: Callable[[str], Awaitable[str]], *, on_checkin=None, max_steps=200) -> dict` — the ready-set loop. Mirrors `advance_goal` (`dispatch/goal.py:134-209`) but graph-shaped: each tick computes the ready set, runs the batch concurrently via `asyncio.gather`, persists per node, recomputes; a `failed` node marks transitive dependents `blocked`. Upstream `result`s are prepended to a node's prompt as context (cap 4000 chars, like `dispatch/mission.py:21`). Write/verify handling is added in Tasks 4/5 — here implement read/synthesize only.
- Consumes: `Run`/`Task`/`TaskEdge` (Task 1), `db.session_scope`, `dispatch.answer.clean_agent_output`.

- [ ] **Step 1: Write the failing tests**

```python
# apps/api/tests/test_dag_driver.py
import asyncio
from sqlmodel import Session
from db import engine
from models import Run, Task, TaskEdge
from dispatch.orchestrator import dag


def _mkrun(nodes, edges):
    with Session(engine) as s:
        run = Run(text="t", mode="mission", status="running"); s.add(run); s.commit(); s.refresh(run)
        for key, kind in nodes:
            s.add(Task(run_id=run.id, key=key, agent="researcher", kind=kind, prompt=f"do {key}"))
        for a, b in edges:
            s.add(TaskEdge(run_id=run.id, src=a, dst=b))
        s.commit(); return run.id


def test_ready_returns_roots_then_unblocks():
    rid = _mkrun([("a", "read"), ("b", "read")], [("a", "b")])
    with Session(engine) as s:
        tasks = list(s.exec(__import__("sqlmodel").select(Task).where(Task.run_id == rid)))
        edges = list(s.exec(__import__("sqlmodel").select(TaskEdge).where(TaskEdge.run_id == rid)))
        assert {t.key for t in dag.ready(tasks, edges)} == {"a"}  # b blocked on a
        for t in tasks:
            if t.key == "a": t.status = "done"
        assert {t.key for t in dag.ready(tasks, edges)} == {"b"}


def test_diamond_runs_parallel_then_join():
    # A -> {B,C} -> D ; record call order, assert B and C both start before D
    rid = _mkrun([("A", "read"), ("B", "read"), ("C", "read"), ("D", "synthesize")],
                 [("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")])
    order = []
    async def runner(prompt):
        key = prompt.split("do ")[-1].split()[0] if "do " in prompt else "?"
        order.append(key); await asyncio.sleep(0); return f"{key}-result"
    asyncio.run(dag.drive_run(rid, runner))
    assert order[0] == "A"
    assert set(order[1:3]) == {"B", "C"}  # parallel middle
    assert order[-1] == "D"


def test_failed_node_blocks_dependents():
    rid = _mkrun([("a", "read"), ("b", "read")], [("a", "b")])
    async def runner(prompt):
        raise RuntimeError("boom")
    asyncio.run(dag.drive_run(rid, runner))
    with Session(engine) as s:
        tasks = {t.key: t.status for t in s.exec(__import__("sqlmodel").select(Task).where(Task.run_id == rid))}
    assert tasks["a"] == "failed" and tasks["b"] == "blocked"
```

- [ ] **Step 2: Run tests → fail** (`ModuleNotFoundError: dispatch.orchestrator`).

- [ ] **Step 3: Implement `dag.py`.** Create the package `__init__.py` (empty) and `dag.py`. Implement `ready()` as the pure function described, and `drive_run()` modeled on `advance_goal` but: (a) load all tasks+edges for the run once per tick; (b) compute `ready()`; (c) for the ready batch (read/synthesize kinds only in this task), build each node's prompt = upstream results (joined, capped 4000) + `task.prompt`, mark `active`, `asyncio.gather` the injected `run(prompt)` calls, `clean_agent_output` each, mark `done`/`failed`, persist per node in a `session_scope`; (d) on `failed`, set every transitive dependent (BFS over edges) to `blocked`; (e) poll `cancel_requested` at the top of each tick (Task 6 deepens this); (f) loop until no `pending`/`ready`/`active` remain, then set `Run.status="done"`. Use `session_scope` writes exactly like `goal.py:187-200`. Keep `run` injected — no agent import here.

- [ ] **Step 4: Run tests → pass** (3 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/api/dispatch/orchestrator/ apps/api/tests/test_dag_driver.py
git commit -m "feat(orchestrator): ready-set DAG driver (read/synthesize nodes)"
```

---

### Task 3: Decompose contract + degradation

**Files:**
- Create: `apps/api/dispatch/orchestrator/decompose.py`
- Test: `apps/api/tests/test_decompose.py`

**Interfaces:**
- Produces: `parse_dag(text: str) -> list[dict] | None` (tolerant JSON like `dispatch/mission.py:49-72`); `validate_dag(nodes: list[dict]) -> list[dict] | None` (topo-sort cycle reject via Kahn; every `read` agent ∈ `MISSION_AGENTS`; `write` agent ∈ `WRITE_AGENTS={"planner"}` (calendar-only v1 — planner owns calendar proposals); `verify`/`synthesize` pinned to `ceo`; `len(nodes)≤8`; exactly one `synthesize` and one `verify` with `verify` depending on `synthesize`; every `depends_on` references a declared key — return None on any failure); `build_dag(run_id, nodes) -> None` (persist `Task`+`TaskEdge` rows); `degrade(run_id, text, mode) -> None` (mission → `_parse_subtasks` ≤4 read + 1 synthesize, or single researcher; goal → single read node — reuse `dispatch/mission.py:_parse_subtasks` and `dispatch/goal.py` single-node fallback).

- [ ] **Step 1: Write the failing tests** (covering: valid JSON → expected nodes; cycle `A→B→A` → None; read-node bound to a non-MISSION agent → None; 9-node DAG → None; missing synthesize/verify pair → None; garbage → None so caller degrades).

```python
# apps/api/tests/test_decompose.py
from dispatch.orchestrator import decompose as D

VALID = '{"nodes":[{"key":"r","agent":"researcher","kind":"read","prompt":"x","depends_on":[]},'\
        '{"key":"s","agent":"ceo","kind":"synthesize","prompt":"x","depends_on":["r"]},'\
        '{"key":"v","agent":"ceo","kind":"verify","prompt":"x","depends_on":["s"]}]}'

def test_valid_dag_parses_and_validates():
    nodes = D.validate_dag(D.parse_dag(VALID))
    assert {n["key"] for n in nodes} == {"r", "s", "v"}

def test_cycle_rejected():
    cyc = '{"nodes":[{"key":"a","agent":"researcher","kind":"read","prompt":"x","depends_on":["b"]},'\
          '{"key":"b","agent":"researcher","kind":"read","prompt":"x","depends_on":["a"]}]}'
    assert D.validate_dag(D.parse_dag(cyc)) is None

def test_read_node_bound_to_write_agent_rejected():
    bad = VALID.replace('"agent":"researcher","kind":"read"', '"agent":"planner","kind":"read"')
    assert D.validate_dag(D.parse_dag(bad)) is None

def test_over_cap_rejected():
    nodes = [{"key": f"n{i}", "agent": "researcher", "kind": "read", "prompt": "x", "depends_on": []} for i in range(9)]
    import json
    assert D.validate_dag(json.loads(json.dumps({"nodes": nodes}))["nodes"]) is None
```

- [ ] **Step 2: Run tests → fail.**

- [ ] **Step 3: Implement `decompose.py`** per the interfaces. Define `WRITE_AGENTS = {"planner"}` with a comment that v1 is calendar-only. Kahn's algorithm for the topo-sort/cycle check. Import `MISSION_AGENTS` and `_parse_subtasks` from `dispatch.mission`.

- [ ] **Step 4: Run tests → pass.**

- [ ] **Step 5: Commit**

```bash
git add apps/api/dispatch/orchestrator/decompose.py apps/api/tests/test_decompose.py
git commit -m "feat(orchestrator): decompose contract — DAG parse, topo/roster/cap validation, degrade"
```

---

### Task 4: Write-node gating + approval callback

**Files:**
- Modify: `apps/api/dispatch/orchestrator/dag.py` (write-node pause), `apps/api/routes/telegram.py` (`_handle_run_callback`)
- Test: `apps/api/tests/test_dag_driver.py`, `apps/api/tests/test_run_callback.py`

**Interfaces:**
- Consumes: `dispatch.cards.{Card, Action, send_card}`, `integrations.google_calendar` write helper (the `user_initiated=True` gate).
- Produces: in `drive_run`, a ready `write` node flips to `awaiting_approval`, emits a Card `[Approve]`/`[Reject]` with `callback_data` `run:approve:{task_id}`/`run:reject:{task_id}`, and is removed from the batch (branch pauses, others continue). New `routes/telegram.py:_handle_run_callback(data, chat_id)` — on `run:approve:{id}` execute the node's write with `user_initiated=True`, mark `done`, relaunch the driver to unblock dependents; on `run:reject:{id}` mark `skipped`, dependents `blocked`/`skipped`.

- [ ] **Step 1: Write the failing tests** — the two safety tests from spec §Write nodes line 113 and §Tests line 212-213:

```python
# apps/api/tests/test_run_callback.py
import asyncio
from unittest.mock import patch
from sqlmodel import Session
from db import engine
from models import Run, Task, TaskEdge
from dispatch.orchestrator import dag


def _run_with_write():
    with Session(engine) as s:
        run = Run(text="t", mode="mission", status="running", chat_id=1); s.add(run); s.commit(); s.refresh(run)
        s.add(Task(run_id=run.id, key="w", agent="planner", kind="write", prompt="create event"))
        s.commit(); return run.id


def test_write_node_pauses_and_never_self_executes():
    rid = _run_with_write()
    with patch("integrations.google_calendar.create_event") as mock_write, \
         patch("dispatch.cards.send_card"):
        asyncio.run(dag.drive_run(rid, lambda p: _async(""), max_steps=5))
        assert mock_write.call_count == 0  # NEVER self-executes
    with Session(engine) as s:
        t = list(s.exec(__import__("sqlmodel").select(Task).where(Task.run_id == rid)))[0]
        assert t.status == "awaiting_approval"


async def _async(v):
    return v
```

(Add a second test in `test_dag_driver.py`: on the approve path — call the new callback handler with `run:approve:{task_id}` — assert `create_event` is called exactly once with `user_initiated=True` and the node becomes `done`. Read `routes/telegram.py` `_handle_goal_callback` (~`:296`) and the existing `goal:`/`op:` prefix dispatch (~`:265-293`) to mirror the handler registration and the allow-list precedence.)

- [ ] **Step 2: Run tests → fail.**

- [ ] **Step 3: Implement** the write-node pause in `drive_run` (before gathering a batch, peel off `kind=="write"` ready nodes → `awaiting_approval` + `send_card`), and `_handle_run_callback` in `routes/telegram.py` wired into the existing prefix dispatch with the `run:` prefix. The write execution calls the calendar helper with `user_initiated=True` — the ONLY place that flag is set. Relaunch the driver after approve (fire-and-forget like `launch_goal`).

- [ ] **Step 4: Run tests → pass** (incl. the no-autonomous-write regression).

- [ ] **Step 5: Commit**

```bash
git add apps/api/dispatch/orchestrator/dag.py apps/api/routes/telegram.py apps/api/tests/test_run_callback.py apps/api/tests/test_dag_driver.py
git commit -m "feat(orchestrator): write-node approval gate (awaiting_approval -> tap -> user_initiated)"
```

---

### Task 5: Verify gate (single critic, one bounded retry)

**Files:** Modify `apps/api/dispatch/orchestrator/dag.py`; Test `apps/api/tests/test_dag_driver.py`

**Interfaces:** After the `synthesize` node is `done`, the `verify` node runs the CEO critic, parsing `{"pass":bool,"reasons":[...]}` (tolerant, like `mission._parse_subtasks`). `pass` → finalize. `fail` → reset the single `synthesize` node to `pending`, append the critic `reasons` to its prompt, rerun it once and re-feed `verify` once, then **finalize regardless** of the second verdict. Parse failure → treat as `pass`.

- [ ] **Step 1: Failing test** — a critic returning `{pass:false}` causes the `synthesize` runner to be called twice and `verify` twice, then the run finalizes; a critic that returns garbage degrades to pass (synthesize called once). Use an injected runner whose responses are keyed by node kind/key.

- [ ] **Step 2: Run → fail. Step 3: Implement** the verify branch in `drive_run` (recognize `kind=="verify"`; bounded retry counter on the run, max 1). **Step 4: Run → pass. Step 5: Commit** `feat(orchestrator): verify gate with one bounded retry`.

---

### Task 6: Cooperative steering, resume, recover_runs + migration

**Files:** Modify `apps/api/dispatch/orchestrator/dag.py`, `apps/api/dispatch/goal.py` (migration + rename), `apps/api/main.py` (lifespan slot); Test `apps/api/tests/test_dag_driver.py`, `apps/api/tests/test_run_migration.py`

**Interfaces:** `cancel_requested` polled at each tick top → `Run.status="aborted"` (mirror `goal.py:153-158`); GUIDANCE appended to the next not-yet-`active` ready node's prompt (mirror `goal.py:112-130`). `recover_runs() -> int` (rename/extend `recover_goals`, `goal.py:290-300`): mark live `running`/`checkin`/`planning` runs `paused` (goal) or reset `active`→`pending` and re-drive (mission); plus the one-shot row migration — each legacy `Goal` → `Run(mode="goal", …)`, each `Milestone(seq=i)` → `Task(key=f"m{i}", kind="read", agent="researcher", status, result)` + chain `TaskEdge(src=f"m{i}", dst=f"m{i+1}")`. Register `recover_runs` in the `main.py` lifespan slot where `recover_goals` is (`main.py:62-67`); keep `recover_goals` as a shim calling `recover_runs`.

- [ ] **Steps:** Failing tests (cancel-at-boundary → `aborted`, no kill; resume-partial → `done` nodes not rerun; migration → one `Run` + N chained `Task`s preserving order/`done`). Implement. Verify. Commit `feat(orchestrator): cooperative steer + resume + recover_runs + Goal/Milestone migration`.

---

### Task 7: Mode surfacing (goal check-ins / mission progress)

**Files:** Modify `apps/api/dispatch/orchestrator/dag.py`; Test `apps/api/tests/test_dag_driver.py`

**Interfaces:** **goal** mode emits a check-in `Card` (`[Continue]`/`[Steer]`/`[Abort]`, reuse `goal.checkin_card` shape with `goal:` verbs) at phase boundaries (after the last read/write node, pre-synthesis; and at finalize). **mission** mode runs silent with a single progress ping ("N nodes dispatched") then the final synthesized report. Pass the surfacing via the `on_checkin`/`progress` callbacks already threaded through the driver.

- [ ] **Steps:** Failing tests (goal mode calls `on_checkin` at the phase boundary; mission mode sends one progress ping + a final report, no per-node check-in). Implement. Verify. Commit `feat(orchestrator): mode-specific surfacing (goal check-ins, mission progress)`.

---

### Task 8: Observability — `routes/runs.py`

**Files:** Create `apps/api/routes/runs.py`; Modify `apps/api/main.py` (include router, drop the `routes/threads.py` stub); Test `apps/api/tests/test_runs_routes.py`

**Interfaces:** `GET /api/runs` → recent runs `[{id, mode, status, node_counts}]`; `GET /api/runs/{id}` → `{run, nodes:[{key,agent,kind,status,result?}], edges:[{src,dst}]}` read straight from `Task`/`TaskEdge`. Replace the dead `routes/threads.py` include in `main.py` with `routes/runs.py` (read `main.py` around the `threads` include — Task E of the overhaul already removed `threads.py`; if it's gone, just add the runs router).

- [ ] **Steps:** Failing test (seed a Run+Tasks+Edges, GET `/api/runs/{id}` returns the DAG with statuses; GET `/api/runs` lists it). Implement with a `TestClient`. Verify. Commit `feat(orchestrator): /api/runs observability endpoints`.

---

### Task 9: Entry points + fold old modules

**Files:** Modify `apps/api/dispatch/dispatcher.py` (mission task-type ~`:161`), `apps/api/routes/telegram.py` (`goal:`/`mission:` entry ~`:651-664`), `apps/api/dispatch/mission.py` + `apps/api/dispatch/goal.py` (thin shims to the engine, keeping `DECOMPOSE_PROMPT`/`SYNTH_PROMPT`/`_parse_subtasks`/`MISSION_AGENTS` + check-in/GUIDANCE logic as the degrade paths); Test `apps/api/tests/test_routes.py`, `apps/api/tests/test_goal.py`, `apps/api/tests/test_mission.py`

**Interfaces:** Add `dispatch/orchestrator/engine.py` `async def run_orchestration(text, *, mode, chat_id) -> dict` that: creates a `Run` + `Job(kind="run")`, runs the CEO decompose, `validate_dag`→`build_dag` or `degrade`, then `drive_run` with the default agent runner (`run_agent_for_answer` per node's agent). Repoint `dispatcher` mission task-type and the `goal:` Telegram entry at `run_orchestration` (mode `mission`/`goal`). Keep `run_mission`/`run_goal`/`advance_goal` importable (shims) so existing tests/imports don't break. **Update existing `test_goal.py`/`test_mission.py`** to the engine's behavior rather than deleting coverage.

- [ ] **Steps:** Failing tests (`mission: X` and `goal: X` both create a `Run` and drive it; a garbage CEO decompose still produces a working run via degrade). Implement. Run the FULL backend suite green. Commit `feat(orchestrator): repoint mission:/goal: at the engine; fold old modules to degrade paths`.

---

### Task 10: Web run-view on the Network tab

**Files:** Modify `apps/web/components/network-graph.tsx`, `apps/web/app/network/page.tsx`, `apps/web/lib/api.ts`, `apps/web/lib/types.ts`; Test `apps/web/test/network-run-view.test.tsx`

**Interfaces:** `api.listRuns()` / `api.getRun(id)` (→ `/api/runs`, `/api/runs/{id}`); `Run`/`RunNode`/`RunEdge` types. Network graph gains a **run view** (toggle on `/network`): given a run id, render `Task` nodes (colored by `status`) and `TaskEdge`s as real agent→agent edges; an edge pulses when its `dst` activates (reuse `subscribeToActivity`, keyed on node `key`). Default fleet view (hub↔agent) unchanged.

- [ ] **Steps:** Failing component/test (render a mocked run → nodes+edges appear; toggle switches views). Implement. `npx tsc --noEmit` + `npx vitest run` green. Commit `feat(web): orchestration run-view on the Network tab`.

---

## Self-Review

- **Spec coverage:** data model (T1), ready-set driver + diamond/parallel + failed-blocks (T2), decompose contract + cycle/roster/cap + degrade (T3), write-node gating + no-autonomous-write regression (T4), verify one-retry (T5), cooperative steer + resume + recover_runs + migration (T6), mode surfacing (T7), `routes/runs.py` observability (T8), entry-point repoint + fold (T9), web run-view (T10). Every spec §Tests item maps to a task.
- **Placeholder scan:** Tasks 5-10 use condensed step blocks (the pattern is established in Tasks 1-4 with full test+impl code); each names exact files, interfaces, and the spec lines to mirror. Implementers read the cited spec sections + code sites for exact code — no "TBD"/"handle edge cases" left vague.
- **Type consistency:** `ready(tasks, edges)`, `drive_run(run_id, run, *, on_checkin, max_steps)`, `parse_dag`/`validate_dag`/`build_dag`/`degrade`, `WRITE_AGENTS={"planner"}`, `run:approve/reject:{task_id}`, `recover_runs()`, `run_orchestration(text, *, mode, chat_id)` are used consistently across tasks. `Run/Task/TaskEdge` field names match spec §Data model exactly.
