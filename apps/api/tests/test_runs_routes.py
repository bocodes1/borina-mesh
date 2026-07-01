"""Observability API for the orchestration engine — read-only views over the
Run / RunTask / TaskEdge tables. GET /api/runs lists recent runs with per-status
node counts; GET /api/runs/{id} returns the full DAG (nodes + edges) with live
statuses. No write route — the engine mutates state, these just read it. Mirrors
test_outreach_routes' TestClient shape checks."""
import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from main import app
from db import session_scope
from models import Run, RunTask, TaskEdge

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clean():
    with session_scope() as s:
        for e in s.exec(select(TaskEdge)).all():
            s.delete(e)
        for t in s.exec(select(RunTask)).all():
            s.delete(t)
        for r in s.exec(select(Run)).all():
            s.delete(r)
        s.commit()
    yield


def _seed_dag():
    """A → {B,C} → D : research/prices feed a synthesize node."""
    with session_scope() as s:
        run = Run(text="mission: scan market", mode="mission", status="running")
        s.add(run)
        s.commit()
        s.refresh(run)
        rid = run.id
        s.add(RunTask(run_id=rid, key="A", agent="researcher", kind="read",
                      prompt="do A", status="done", result="A-result"))
        s.add(RunTask(run_id=rid, key="B", agent="researcher", kind="read",
                      prompt="do B", status="done", result="B-result"))
        s.add(RunTask(run_id=rid, key="C", agent="trader", kind="read",
                      prompt="do C", status="active"))
        s.add(RunTask(run_id=rid, key="D", agent="ceo", kind="synthesize",
                      prompt="do D", status="pending"))
        for a, b in [("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")]:
            s.add(TaskEdge(run_id=rid, src=a, dst=b))
        s.commit()
        return rid


def test_list_runs():
    rid = _seed_dag()
    resp = client.get("/api/runs")
    assert resp.status_code == 200
    runs = resp.json()
    assert isinstance(runs, list)
    row = next(r for r in runs if r["id"] == rid)
    assert row["mode"] == "mission"
    assert row["status"] == "running"
    # node_counts is a status->count map summing to the 4 seeded nodes
    assert sum(row["node_counts"].values()) == 4
    assert row["node_counts"].get("done") == 2


def test_get_run_returns_dag():
    rid = _seed_dag()
    resp = client.get(f"/api/runs/{rid}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["run"]["id"] == rid
    assert body["run"]["mode"] == "mission"
    nodes = {n["key"]: n for n in body["nodes"]}
    assert set(nodes) == {"A", "B", "C", "D"}
    assert nodes["A"]["agent"] == "researcher"
    assert nodes["A"]["kind"] == "read"
    assert nodes["A"]["status"] == "done"
    assert nodes["A"]["result"] == "A-result"
    assert nodes["D"]["kind"] == "synthesize"
    edges = {(e["src"], e["dst"]) for e in body["edges"]}
    assert edges == {("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")}


def test_get_run_404():
    resp = client.get("/api/runs/999999")
    assert resp.status_code == 404
