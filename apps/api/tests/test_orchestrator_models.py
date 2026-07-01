"""Task 1 — Run / RunTask / TaskEdge data model round-trip.

NOTE: the spec/plan name the orchestrator node `Task`, but models.py already
has a `Task` (the personal daily-task table, used by planner/operator/daily
routes). To avoid colliding with that live model we name the orchestrator node
`RunTask` (table "runtask"); fields are otherwise exactly per spec §Data model.
"""
from sqlmodel import Session, select
from db import engine
from models import Run, RunTask, TaskEdge


def test_run_task_edge_roundtrip():
    with Session(engine) as s:
        run = Run(text="mission: scan market", mode="mission", status="running")
        s.add(run)
        s.commit()
        s.refresh(run)
        s.add(RunTask(run_id=run.id, key="research", agent="researcher", kind="read", prompt="..."))
        s.add(RunTask(run_id=run.id, key="synth", agent="ceo", kind="synthesize", prompt="..."))
        s.add(TaskEdge(run_id=run.id, src="research", dst="synth"))
        s.commit()
        tasks = s.exec(select(RunTask).where(RunTask.run_id == run.id)).all()
        edges = s.exec(select(TaskEdge).where(TaskEdge.run_id == run.id)).all()
        assert {t.key for t in tasks} == {"research", "synth"}
        assert (edges[0].src, edges[0].dst) == ("research", "synth")
        assert {t.status for t in tasks} == {"pending"}  # default


def test_run_defaults():
    with Session(engine) as s:
        run = Run(text="goal: ship it")
        s.add(run)
        s.commit()
        s.refresh(run)
        assert run.mode == "mission"
        assert run.status == "planning"
        assert run.cancel_requested is False
        assert run.created_at is not None and run.updated_at is not None
