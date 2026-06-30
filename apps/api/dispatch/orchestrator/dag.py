"""The DAG driver — a ready-set loop over a Run's RunTask/TaskEdge graph.

Replaces the goal runner's linear cursor walk (`dispatch/goal.py:134-209`) with a
ready-set loop: each tick recomputes the set of nodes whose every upstream is
`done`, runs that batch concurrently, persists per node, and recomputes. Parallel
vs. sequential falls out of the graph for free — independent branches enter the
ready set together; dependent branches serialize.

The per-node runner is INJECTED (`run: Callable[[str], Awaitable[str]]`) — the
goal runner's testability seam — so the whole engine unit-tests without spawning
agents. Cooperative cancel only: `cancel_requested` is polled at each tick top.

Task 2 implements read/synthesize nodes. Write-node gating (Task 4) and the
verify gate (Task 5) extend `drive_run` later.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Awaitable, Callable, Optional

from sqlmodel import select

from db import session_scope
from models import Run, RunTask, TaskEdge

_RESULT_CAP = 4000  # chars of each upstream result fed downstream (mirrors mission._RESULT_CAP)


def ready(tasks: list[RunTask], edges: list[TaskEdge]) -> list[RunTask]:
    """Pure: the `pending` tasks whose every upstream `src` node is `done`.

    A node with no incoming edge is ready immediately (a root). Edges whose
    `src` key is unknown are treated as unsatisfiable (defensive — a validated
    DAG never has dangling edges)."""
    status_by_key = {t.key: t.status for t in tasks}
    upstreams: dict[str, list[str]] = {}
    for e in edges:
        upstreams.setdefault(e.dst, []).append(e.src)
    out = []
    for t in tasks:
        if t.status != "pending":
            continue
        deps = upstreams.get(t.key, [])
        if all(status_by_key.get(src) == "done" for src in deps):
            out.append(t)
    return out


def _transitive_dependents(start_key: str, edges: list[TaskEdge]) -> set[str]:
    """BFS over edges: every key reachable downstream from `start_key`."""
    children: dict[str, list[str]] = {}
    for e in edges:
        children.setdefault(e.src, []).append(e.dst)
    seen: set[str] = set()
    frontier = list(children.get(start_key, []))
    while frontier:
        k = frontier.pop()
        if k in seen:
            continue
        seen.add(k)
        frontier.extend(children.get(k, []))
    return seen


def _snapshot(run_id: int) -> dict:
    with session_scope() as s:
        run = s.get(Run, run_id)
        if not run:
            return {"status": "missing"}
        tasks = s.exec(select(RunTask).where(RunTask.run_id == run_id)).all()
        return {
            "id": run.id,
            "mode": run.mode,
            "status": run.status,
            "nodes": [
                {"key": t.key, "agent": t.agent, "kind": t.kind, "status": t.status, "result": t.result}
                for t in tasks
            ],
        }


async def drive_run(
    run_id: int,
    run: Callable[[str], Awaitable[str]],
    *,
    on_checkin: Optional[Callable[[dict], None]] = None,
    max_steps: int = 200,
) -> dict:
    """Drive the run's DAG to completion. Each tick: poll cancel, compute the
    ready set, run the batch concurrently through the injected `run`, persist per
    node, mark a failed node's transitive dependents `blocked`, recompute. Loops
    until no node is `pending`/`ready`/`active`, then sets `Run.status="done"`.

    The per-node runner is injected so this is unit-testable without agents."""
    from dispatch.answer import clean_agent_output

    steps = 0
    while steps < max_steps:
        steps += 1

        # ── tick top: poll cancel, compute ready set, claim the batch ──────────
        with session_scope() as s:
            run_row = s.get(Run, run_id)
            if not run_row:
                return {"status": "missing"}
            if run_row.cancel_requested:
                run_row.status = "aborted"
                run_row.updated_at = datetime.utcnow()
                s.add(run_row)
                s.commit()
                break

            tasks = list(s.exec(select(RunTask).where(RunTask.run_id == run_id)))
            edges = list(s.exec(select(TaskEdge).where(TaskEdge.run_id == run_id)))
            rdy = ready(tasks, edges)

            if not rdy:
                # Nothing runnable: finalize. A node in `awaiting_approval` means
                # the run is parked on a write-node tap (paused, NOT done). A
                # node still `pending`/`active` here is blocked behind a
                # failed/blocked upstream that ready() already excluded.
                if any(t.status == "awaiting_approval" for t in tasks):
                    run_row.status = "paused"
                elif any(t.status in ("pending", "active") for t in tasks):
                    run_row.status = "blocked"
                else:
                    run_row.status = "done"
                run_row.updated_at = datetime.utcnow()
                s.add(run_row)
                s.commit()
                break

            result_by_key = {t.key: (t.result or "") for t in tasks}
            upstreams: dict[str, list[str]] = {}
            for e in edges:
                upstreams.setdefault(e.dst, []).append(e.src)

            chat_id = run_row.chat_id
            batch = []        # (task_id, key, prompt) — read/synthesize/verify
            write_cards = []  # (task_id, key, intent, ctx_parts) — peeled writes
            for t in rdy:
                ctx_parts = []
                for src in upstreams.get(t.key, []):
                    body = (result_by_key.get(src) or "").strip()
                    if body:
                        ctx_parts.append(f"## Context from {src}\n\n{body[:_RESULT_CAP]}")
                # Write nodes NEVER run here — they pause for an approval tap.
                if t.kind == "write":
                    t.status = "awaiting_approval"
                    t.started_at = datetime.utcnow()
                    s.add(t)
                    write_cards.append((t.id, t.key, t.prompt, ctx_parts))
                    continue
                prompt = ("\n\n".join(ctx_parts) + "\n\n" + t.prompt) if ctx_parts else t.prompt
                t.status = "active"
                t.started_at = datetime.utcnow()
                s.add(t)
                batch.append((t.id, t.key, prompt))
            s.commit()

        # ── emit approval Cards for any peeled write nodes (post-commit) ────────
        for (tid, key, intent, ctx_parts) in write_cards:
            if not chat_id:
                continue
            from dispatch.cards import Card, Action, send_card
            lines = [intent[:200]] + [c[:200] for c in ctx_parts[:3]]
            card = Card(
                headline=f"Approve write: {key}",
                lines=lines,
                actions=[Action("Approve", f"run:approve:{tid}"), Action("Reject", f"run:reject:{tid}")],
            )
            try:
                send_card(chat_id, card)
            except Exception:  # noqa: BLE001
                pass

        # ── run the batch concurrently (outside the session; may be slow) ──────
        results = await asyncio.gather(
            *(run(prompt) for (_, _, prompt) in batch), return_exceptions=True
        )

        # ── persist per node; mark failed nodes' dependents blocked ────────────
        with session_scope() as s:
            edges = list(s.exec(select(TaskEdge).where(TaskEdge.run_id == run_id)))
            failed_keys = []
            for (tid, key, _), res in zip(batch, results):
                t = s.get(RunTask, tid)
                if t is None:
                    continue
                if isinstance(res, Exception):
                    t.status = "failed"
                    t.result = f"(node failed: {res})"[:_RESULT_CAP]
                    failed_keys.append(key)
                else:
                    cleaned = clean_agent_output(res) if res else ""
                    t.status = "done"
                    t.result = cleaned[:_RESULT_CAP]
                t.completed_at = datetime.utcnow()
                s.add(t)

            if failed_keys:
                blocked = set()
                for fk in failed_keys:
                    blocked |= _transitive_dependents(fk, edges)
                if blocked:
                    for t in s.exec(select(RunTask).where(RunTask.run_id == run_id)):
                        if t.key in blocked and t.status in ("pending", "ready"):
                            t.status = "blocked"
                            s.add(t)
            s.commit()

        if on_checkin:
            snap = _snapshot(run_id)
            try:
                on_checkin(snap)
            except Exception:  # noqa: BLE001
                pass

    return _snapshot(run_id)


# ── write-node approval lifecycle (driven from the Telegram callback) ───────────
# NOTE: the actual side-effecting write (`user_initiated=True`) lives in the
# `routes/telegram.py` callback handler — the engine never sets that flag. These
# helpers only flip persisted state and unblock the graph after a real tap.

def complete_write(task_id: int, result: Optional[str] = None) -> Optional[int]:
    """Mark an approved write node `done` (its write already ran in the callback).
    Returns the run id so the caller can relaunch the driver to unblock dependents."""
    with session_scope() as s:
        t = s.get(RunTask, task_id)
        if t is None:
            return None
        t.status = "done"
        t.result = (result or "(write approved & executed)")[:_RESULT_CAP]
        t.completed_at = datetime.utcnow()
        s.add(t)
        s.commit()
        return t.run_id


def reject_write(task_id: int) -> Optional[int]:
    """Mark a rejected write node `skipped` and its transitive dependents
    `blocked` (they depended on an action that never happened). Returns run id."""
    with session_scope() as s:
        t = s.get(RunTask, task_id)
        if t is None:
            return None
        run_id = t.run_id
        t.status = "skipped"
        t.completed_at = datetime.utcnow()
        s.add(t)
        edges = list(s.exec(select(TaskEdge).where(TaskEdge.run_id == run_id)))
        blocked = _transitive_dependents(t.key, edges)
        if blocked:
            for d in s.exec(select(RunTask).where(RunTask.run_id == run_id)):
                if d.key in blocked and d.status in ("pending", "ready"):
                    d.status = "blocked"
                    s.add(d)
        s.commit()
        return run_id


async def _drive_default(run_id: int) -> dict:
    """Relaunch a paused run with the default per-node runner.

    v1 routes resumed read/synthesize nodes through the read-only researcher
    answer pipeline; Task 9's engine replaces this with the per-node agent
    runner. A relaunch only fires after an approval/reject tap, so it never
    re-runs `done` nodes (their `result` is persisted)."""
    from dispatch.answer import run_agent_for_answer

    with session_scope() as s:
        r = s.get(Run, run_id)
        job_id = (r.job_id or 0) if r else 0

    async def runner(prompt: str) -> str:
        return await run_agent_for_answer("researcher", prompt, job_id)

    return await drive_run(run_id, runner)


def launch_run(run_id: int) -> bool:
    """Schedule `_drive_default` on the running event loop (fire-and-forget),
    mirroring `goal.launch_goal`. Returns False if there is no loop (tests/sync)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False
    loop.create_task(_drive_default(run_id))
    return True
