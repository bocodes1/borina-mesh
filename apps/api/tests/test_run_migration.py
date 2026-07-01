"""Task 6 — recover_runs + one-shot Goal/Milestone → Run/RunTask/TaskEdge migration.

A legacy Goal + N Milestones migrate to one Run(mode="goal") + N RunTasks chained
by TaskEdge, preserving order and per-node status/result. recover_runs() pauses
goal-mode runs (a Continue tap resumes) and resets mission in-flight nodes to
pending so the ready-set loop reruns only non-done work. recover_goals() is now a
back-compat shim that still pauses legacy live Goal rows.
"""
from sqlmodel import Session, select

from db import engine
from models import Goal, Milestone, Run, RunTask, TaskEdge
from dispatch import goal as G


def test_goal_migrates_to_run_with_chained_tasks():
    with Session(engine) as s:
        g = Goal(text="ship the feature", status="paused", chat_id=9)
        s.add(g)
        s.commit()
        s.refresh(g)
        s.add(Milestone(goal_id=g.id, seq=0, title="research", status="done", result="found"))
        s.add(Milestone(goal_id=g.id, seq=1, title="draft", status="done", result="drafted"))
        s.add(Milestone(goal_id=g.id, seq=2, title="ship", status="pending"))
        s.commit()

    n = G.migrate_goals_to_runs()
    assert n >= 1

    with Session(engine) as s:
        runs = s.exec(select(Run).where(Run.mode == "goal", Run.text == "ship the feature")).all()
        assert len(runs) == 1
        run = runs[0]
        tasks = {t.key: t for t in s.exec(select(RunTask).where(RunTask.run_id == run.id))}
        assert set(tasks) == {"m0", "m1", "m2"}
        assert all(t.kind == "read" and t.agent == "researcher" for t in tasks.values())
        assert tasks["m0"].status == "done" and tasks["m0"].result == "found"
        assert tasks["m1"].status == "done" and tasks["m1"].result == "drafted"
        assert tasks["m2"].status == "pending"
        edges = {(e.src, e.dst) for e in s.exec(select(TaskEdge).where(TaskEdge.run_id == run.id))}
        assert edges == {("m0", "m1"), ("m1", "m2")}  # linear chain preserves order


def test_migration_is_idempotent():
    with Session(engine) as s:
        g = Goal(text="unique-goal-idempotent-xyz", status="done", chat_id=1)
        s.add(g)
        s.commit()
        s.refresh(g)
        s.add(Milestone(goal_id=g.id, seq=0, title="only", status="done"))
        s.commit()

    G.migrate_goals_to_runs()
    G.migrate_goals_to_runs()  # second pass must NOT duplicate

    with Session(engine) as s:
        runs = s.exec(select(Run).where(Run.text == "unique-goal-idempotent-xyz")).all()
    assert len(runs) == 1


def test_recover_runs_pauses_goal_mode_run():
    with Session(engine) as s:
        run = Run(text="a goal run", mode="goal", status="running")
        s.add(run)
        s.commit()
        s.refresh(run)
        rid = run.id

    G.recover_runs()

    with Session(engine) as s:
        run = s.get(Run, rid)
    assert run.status == "paused"  # Continue tap resumes


def test_recover_runs_resets_mission_active_to_pending():
    with Session(engine) as s:
        run = Run(text="a mission run", mode="mission", status="running")
        s.add(run)
        s.commit()
        s.refresh(run)
        rid = run.id
        s.add(RunTask(run_id=rid, key="a", agent="researcher", kind="read", prompt="do a",
                      status="done", result="done-a"))
        s.add(RunTask(run_id=rid, key="b", agent="researcher", kind="read", prompt="do b",
                      status="active"))  # in-flight at the crash
        s.commit()

    G.recover_runs()

    with Session(engine) as s:
        tasks = {t.key: t.status for t in s.exec(select(RunTask).where(RunTask.run_id == rid))}
    assert tasks["a"] == "done"      # completed node untouched
    assert tasks["b"] == "pending"   # in-flight reset for an idempotent rerun


def test_recover_goals_shim_still_pauses_legacy_goal():
    gid = G.create_goal("interrupted-legacy", chat_id=None)
    G.set_milestones(gid, ["a"])  # status -> running
    n = G.recover_goals()
    assert n >= 1
    assert G.get_goal(gid)["status"] == "paused"
