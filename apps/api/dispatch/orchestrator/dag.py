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
                # Nothing runnable: finalize. (No pending/ready/active remain — a
                # node still `pending` here is blocked behind a failed/blocked
                # upstream that ready() already excluded.)
                if any(t.status in ("pending", "active") for t in tasks):
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

            batch = []  # (task_id, key, prompt)
            for t in rdy:
                ctx_parts = []
                for src in upstreams.get(t.key, []):
                    body = (result_by_key.get(src) or "").strip()
                    if body:
                        ctx_parts.append(f"## Context from {src}\n\n{body[:_RESULT_CAP]}")
                prompt = ("\n\n".join(ctx_parts) + "\n\n" + t.prompt) if ctx_parts else t.prompt
                t.status = "active"
                t.started_at = datetime.utcnow()
                s.add(t)
                batch.append((t.id, t.key, prompt))
            s.commit()

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
