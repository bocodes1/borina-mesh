"""Orchestration-run observability — read-only views over Run / RunTask /
TaskEdge. Replaces the dead routes/threads.py stub. The driver
(dispatch/orchestrator/dag.py) persists all state; these endpoints just read it
for the Network run-view and the Jobs tab.

- GET /api/runs        → recent runs with per-status node counts.
- GET /api/runs/{id}   → the full DAG: {run, nodes, edges} with live statuses.
"""
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from db import get_session
from models import Run, RunTask, TaskEdge

router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.get("")
async def list_runs(limit: int = 50, session: Session = Depends(get_session)):
    """Recent runs, newest first, each with a status->count node map."""
    runs = session.exec(select(Run).order_by(Run.created_at.desc()).limit(limit)).all()
    out = []
    for run in runs:
        statuses = session.exec(
            select(RunTask.status).where(RunTask.run_id == run.id)
        ).all()
        out.append({
            "id": run.id,
            "mode": run.mode,
            "status": run.status,
            "node_counts": dict(Counter(statuses)),
            "created_at": run.created_at,
            "updated_at": run.updated_at,
        })
    return out


@router.get("/{run_id}")
async def get_run(run_id: int, session: Session = Depends(get_session)):
    """The full DAG for one run, read straight from RunTask/TaskEdge."""
    run = session.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    tasks = session.exec(select(RunTask).where(RunTask.run_id == run_id)).all()
    edges = session.exec(select(TaskEdge).where(TaskEdge.run_id == run_id)).all()
    return {
        "run": run,
        "nodes": [
            {
                "key": t.key,
                "agent": t.agent,
                "kind": t.kind,
                "status": t.status,
                "result": t.result,
            }
            for t in tasks
        ],
        "edges": [{"src": e.src, "dst": e.dst} for e in edges],
    }
