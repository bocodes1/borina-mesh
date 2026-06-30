"""Task 2 — ready-set + DAG driver core.

NOTE: the spec/plan name the orchestrator node `Task`; models.py names it
`RunTask` (the personal daily-task `Task` already owns that name). Tests below
mirror the plan's cases against `RunTask`.
"""
import asyncio

from sqlmodel import Session, select

from db import engine
from models import Run, RunTask, TaskEdge
from dispatch.orchestrator import dag


def _mkrun(nodes, edges):
    with Session(engine) as s:
        run = Run(text="t", mode="mission", status="running")
        s.add(run)
        s.commit()
        s.refresh(run)
        for key, kind in nodes:
            s.add(RunTask(run_id=run.id, key=key, agent="researcher", kind=kind, prompt=f"do {key}"))
        for a, b in edges:
            s.add(TaskEdge(run_id=run.id, src=a, dst=b))
        s.commit()
        return run.id


def test_ready_returns_roots_then_unblocks():
    rid = _mkrun([("a", "read"), ("b", "read")], [("a", "b")])
    with Session(engine) as s:
        tasks = list(s.exec(select(RunTask).where(RunTask.run_id == rid)))
        edges = list(s.exec(select(TaskEdge).where(TaskEdge.run_id == rid)))
        assert {t.key for t in dag.ready(tasks, edges)} == {"a"}  # b blocked on a
        for t in tasks:
            if t.key == "a":
                t.status = "done"
        assert {t.key for t in dag.ready(tasks, edges)} == {"b"}


def test_diamond_runs_parallel_then_join():
    # A -> {B,C} -> D ; record call order, assert B and C both start before D
    rid = _mkrun(
        [("A", "read"), ("B", "read"), ("C", "read"), ("D", "synthesize")],
        [("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")],
    )
    order = []

    async def runner(prompt):
        key = prompt.split("do ")[-1].split()[0] if "do " in prompt else "?"
        order.append(key)
        await asyncio.sleep(0)
        return f"{key}-result"

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
        tasks = {t.key: t.status for t in s.exec(select(RunTask).where(RunTask.run_id == rid))}
    assert tasks["a"] == "failed" and tasks["b"] == "blocked"


def test_upstream_results_feed_downstream_and_run_done():
    rid = _mkrun([("a", "read"), ("b", "synthesize")], [("a", "b")])
    seen = {}

    async def runner(prompt):
        if "do a" in prompt:
            seen["a"] = prompt
            return "alpha-result"
        seen["b"] = prompt
        return "beta-result"

    asyncio.run(dag.drive_run(rid, runner))
    # b's prompt carries a's cleaned result as upstream context.
    assert "alpha-result" in seen["b"]
    with Session(engine) as s:
        run = s.get(Run, rid)
        tasks = {t.key: t for t in s.exec(select(RunTask).where(RunTask.run_id == rid))}
    assert run.status == "done"
    assert tasks["a"].status == "done" and tasks["a"].result == "alpha-result"
    assert tasks["b"].status == "done"
