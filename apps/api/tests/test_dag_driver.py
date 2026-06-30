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


def test_write_node_peeled_to_awaiting_approval_with_card(monkeypatch):
    # A ready write node is removed from the batch, flips to awaiting_approval,
    # and emits one approval Card — its runner is never invoked.
    from unittest.mock import patch

    with Session(engine) as s:
        run = Run(text="t", mode="mission", status="running", chat_id=7)
        s.add(run)
        s.commit()
        s.refresh(run)
        rid = run.id
        s.add(RunTask(run_id=rid, key="w", agent="planner", kind="write", prompt="create event"))
        s.commit()

    called = []

    async def runner(prompt):
        called.append(prompt)
        return "should-not-run"

    with patch("dispatch.cards.send_card") as mock_card:
        asyncio.run(dag.drive_run(rid, runner, max_steps=5))
        assert mock_card.call_count == 1
        data = [a.data for a in mock_card.call_args.args[1].actions]
        with Session(engine) as s:
            tid = s.exec(select(RunTask).where(RunTask.run_id == rid)).first().id
        assert data == [f"run:approve:{tid}", f"run:reject:{tid}"]

    assert called == []  # write node never runs
    with Session(engine) as s:
        run = s.get(Run, rid)
        t = s.exec(select(RunTask).where(RunTask.run_id == rid)).first()
    assert t.status == "awaiting_approval"
    assert run.status == "paused"


def _mkrun_with_verify():
    # r (read) -> s (synthesize) -> v (verify)
    with Session(engine) as s:
        run = Run(text="t", mode="mission", status="running")
        s.add(run)
        s.commit()
        s.refresh(run)
        rid = run.id
        s.add(RunTask(run_id=rid, key="r", agent="researcher", kind="read", prompt="do r"))
        s.add(RunTask(run_id=rid, key="s", agent="ceo", kind="synthesize", prompt="do s"))
        s.add(RunTask(run_id=rid, key="v", agent="ceo", kind="verify", prompt="do v"))
        s.add(TaskEdge(run_id=rid, src="r", dst="s"))
        s.add(TaskEdge(run_id=rid, src="s", dst="v"))
        s.commit()
        return rid


def test_verify_fail_triggers_one_retry_then_finalizes():
    rid = _mkrun_with_verify()
    calls = {"r": 0, "s": 0, "v": 0}

    async def runner(prompt):
        if "do v" in prompt:
            calls["v"] += 1
            return '{"pass": false, "reasons": ["needs more detail"]}'
        if "do s" in prompt:
            calls["s"] += 1
            return "synthesis text"
        calls["r"] += 1
        return "research"

    asyncio.run(dag.drive_run(rid, runner))
    # fail verdict → synthesize re-run exactly once more, verify re-fed once more.
    assert calls["s"] == 2
    assert calls["v"] == 2
    with Session(engine) as s:
        run = s.get(Run, rid)
        tasks = {t.key: t.status for t in s.exec(select(RunTask).where(RunTask.run_id == rid))}
    assert run.status == "done"  # finalizes regardless of the second verdict
    assert tasks["s"] == "done" and tasks["v"] == "done"


def test_verify_parse_error_degrades_to_pass():
    rid = _mkrun_with_verify()
    calls = {"r": 0, "s": 0, "v": 0}

    async def runner(prompt):
        if "do v" in prompt:
            calls["v"] += 1
            return "not json at all"
        if "do s" in prompt:
            calls["s"] += 1
            return "synthesis text"
        calls["r"] += 1
        return "research"

    asyncio.run(dag.drive_run(rid, runner))
    # garbage verdict degrades to pass → no retry.
    assert calls["s"] == 1
    assert calls["v"] == 1
    with Session(engine) as s:
        run = s.get(Run, rid)
    assert run.status == "done"


# ── Task 6: cooperative steering + resume ───────────────────────────────────────
def test_cancel_mid_run_stops_at_next_boundary_no_kill():
    # cancel_requested flipped while a node is in flight → the in-flight node
    # finishes, the run aborts at the NEXT tick boundary, downstream never starts.
    rid = _mkrun([("a", "read"), ("b", "read")], [("a", "b")])
    ran = []

    async def runner(prompt):
        ran.append(prompt)
        if "do a" in prompt:
            dag.request_cancel(rid)  # cooperative flag — NOT a kill
        return "ok"

    asyncio.run(dag.drive_run(rid, runner))
    with Session(engine) as s:
        run = s.get(Run, rid)
        tasks = {t.key: t.status for t in s.exec(select(RunTask).where(RunTask.run_id == rid))}
    assert run.status == "aborted"
    assert any("do a" in p for p in ran)        # a ran (in-flight finished)
    assert not any("do b" in p for p in ran)    # b never started — stopped at boundary
    assert tasks["a"] == "done"
    assert tasks["b"] == "pending"               # left for resume, not killed


def test_guidance_appends_to_next_ready_node_and_resumes():
    rid = _mkrun([("a", "read"), ("b", "read")], [("a", "b")])
    with Session(engine) as s:
        r = s.get(Run, rid)
        r.status = "checkin"
        r.cancel_requested = True
        s.add(r)
        s.commit()

    dag.add_guidance(rid, "focus on X")

    with Session(engine) as s:
        run = s.get(Run, rid)
        tasks = {t.key: t for t in s.exec(select(RunTask).where(RunTask.run_id == rid))}
    # appended to the next not-yet-active ready node (root "a"); run resumes.
    assert "focus on X" in tasks["a"].prompt
    assert "focus on X" not in tasks["b"].prompt
    assert run.status == "running"
    assert run.cancel_requested is False


def test_resume_does_not_rerun_done_nodes():
    # Mirrors a restart mid-run: "a" already done, "b" pending. Re-driving must
    # never re-run "a" and must feed a's persisted result downstream to "b".
    rid = _mkrun([("a", "read"), ("b", "synthesize")], [("a", "b")])
    with Session(engine) as s:
        t = s.exec(select(RunTask).where(RunTask.run_id == rid, RunTask.key == "a")).first()
        t.status = "done"
        t.result = "already-a"
        s.add(t)
        s.commit()

    ran = []

    async def runner(prompt):
        ran.append(prompt)
        return "b-out"

    asyncio.run(dag.drive_run(rid, runner))
    assert not any("do a" in p for p in ran)     # done node never rerun
    assert any("do b" in p for p in ran)
    assert any("already-a" in p for p in ran)    # persisted upstream result fed down
    with Session(engine) as s:
        run = s.get(Run, rid)
    assert run.status == "done"
