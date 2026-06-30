"""Task 3 — decompose contract: parse DAG JSON, validate (topo/roster/cap),
build_dag persistence, and graceful degradation to the mission/goal fallbacks."""
import json

from sqlmodel import Session, select

from db import engine
from models import Run, RunTask, TaskEdge
from dispatch.orchestrator import decompose as D

VALID = (
    '{"nodes":[{"key":"r","agent":"researcher","kind":"read","prompt":"x","depends_on":[]},'
    '{"key":"s","agent":"ceo","kind":"synthesize","prompt":"x","depends_on":["r"]},'
    '{"key":"v","agent":"ceo","kind":"verify","prompt":"x","depends_on":["s"]}]}'
)


def test_valid_dag_parses_and_validates():
    nodes = D.validate_dag(D.parse_dag(VALID))
    assert {n["key"] for n in nodes} == {"r", "s", "v"}


def test_cycle_rejected():
    cyc = (
        '{"nodes":[{"key":"a","agent":"researcher","kind":"read","prompt":"x","depends_on":["b"]},'
        '{"key":"b","agent":"researcher","kind":"read","prompt":"x","depends_on":["a"]}]}'
    )
    assert D.validate_dag(D.parse_dag(cyc)) is None


def test_read_node_bound_to_write_agent_rejected():
    bad = VALID.replace('"agent":"researcher","kind":"read"', '"agent":"planner","kind":"read"')
    assert D.validate_dag(D.parse_dag(bad)) is None


def test_over_cap_rejected():
    nodes = [
        {"key": f"n{i}", "agent": "researcher", "kind": "read", "prompt": "x", "depends_on": []}
        for i in range(9)
    ]
    assert D.validate_dag(json.loads(json.dumps({"nodes": nodes}))["nodes"]) is None


def test_missing_synth_verify_pair_rejected():
    only_reads = (
        '{"nodes":[{"key":"a","agent":"researcher","kind":"read","prompt":"x","depends_on":[]},'
        '{"key":"b","agent":"trader","kind":"read","prompt":"x","depends_on":[]}]}'
    )
    assert D.validate_dag(D.parse_dag(only_reads)) is None


def test_dangling_depends_on_rejected():
    bad = (
        '{"nodes":[{"key":"r","agent":"researcher","kind":"read","prompt":"x","depends_on":["ghost"]},'
        '{"key":"s","agent":"ceo","kind":"synthesize","prompt":"x","depends_on":["r"]},'
        '{"key":"v","agent":"ceo","kind":"verify","prompt":"x","depends_on":["s"]}]}'
    )
    assert D.validate_dag(D.parse_dag(bad)) is None


def test_verify_must_depend_on_synthesize():
    bad = (
        '{"nodes":[{"key":"r","agent":"researcher","kind":"read","prompt":"x","depends_on":[]},'
        '{"key":"s","agent":"ceo","kind":"synthesize","prompt":"x","depends_on":["r"]},'
        '{"key":"v","agent":"ceo","kind":"verify","prompt":"x","depends_on":["r"]}]}'
    )
    assert D.validate_dag(D.parse_dag(bad)) is None


def test_garbage_returns_none_so_caller_degrades():
    assert D.parse_dag("not json at all") is None
    assert D.validate_dag(None) is None


def _mkrun(mode="mission"):
    with Session(engine) as s:
        run = Run(text="t", mode=mode, status="planning")
        s.add(run)
        s.commit()
        s.refresh(run)
        return run.id


def test_build_dag_persists_nodes_and_edges():
    rid = _mkrun()
    D.build_dag(rid, D.validate_dag(D.parse_dag(VALID)))
    with Session(engine) as s:
        tasks = {t.key: t for t in s.exec(select(RunTask).where(RunTask.run_id == rid))}
        edges = {(e.src, e.dst) for e in s.exec(select(TaskEdge).where(TaskEdge.run_id == rid))}
    assert set(tasks) == {"r", "s", "v"}
    assert tasks["v"].kind == "verify" and tasks["v"].agent == "ceo"
    assert edges == {("r", "s"), ("s", "v")}


def test_degrade_mission_builds_read_plus_synthesize():
    rid = _mkrun("mission")
    D.degrade(rid, "scan the market for me", "mission")
    with Session(engine) as s:
        tasks = list(s.exec(select(RunTask).where(RunTask.run_id == rid)))
    kinds = sorted(t.kind for t in tasks)
    assert "synthesize" in kinds and "read" in kinds
    assert all(t.kind != "read" or t.agent in __import__("dispatch.mission", fromlist=["MISSION_AGENTS"]).MISSION_AGENTS for t in tasks)


def test_degrade_goal_builds_single_read_node():
    rid = _mkrun("goal")
    D.degrade(rid, "grow the newsletter", "goal")
    with Session(engine) as s:
        tasks = list(s.exec(select(RunTask).where(RunTask.run_id == rid)))
    assert len(tasks) == 1
    assert tasks[0].kind == "read" and tasks[0].agent == "researcher"
