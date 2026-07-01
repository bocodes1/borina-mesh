"""Task 9 — the orchestration engine entry point.

`run_orchestration(text, *, mode, chat_id)` creates a Run + Job(kind="run"), runs
the CEO decompose, validates→builds the DAG (or degrades on garbage), then drives
it with the default per-node agent runner. `mission:` and `goal:` are two modes of
the one engine. The per-node runner is injected via `engine._run_node` so the
whole thing unit-tests without spawning agents.
"""
import asyncio

import pytest
from sqlmodel import Session, select

import models  # noqa: F401 — register tables
from db import engine as db_engine
from models import Job, Run, RunTask
from dispatch.orchestrator import engine as E

VALID_DAG = (
    '{"nodes":['
    '{"key":"r","agent":"researcher","kind":"read","prompt":"dig","depends_on":[]},'
    '{"key":"synth","agent":"ceo","kind":"synthesize","prompt":"write the report","depends_on":["r"]},'
    '{"key":"verify","agent":"ceo","kind":"verify","prompt":"verify the report","depends_on":["synth"]}'
    "]}"
)


def _patch_node(monkeypatch, decompose_out):
    """Replace the engine's per-node runner with a stub keyed by agent/kind so no
    real agent spawns. `decompose_out` is what the CEO returns for the decompose."""
    calls = []

    async def fake_node(agent, prompt, job_id):
        calls.append((agent, prompt))
        if agent == "ceo" and E.DECOMPOSE_MARKER in prompt:
            return decompose_out
        if agent == "ceo" and "verify" in prompt.lower():
            return '{"pass": true}'
        if agent == "ceo":
            return "Final synthesized report."
        return f"{agent} findings"

    monkeypatch.setattr(E, "_run_node", fake_node)
    return calls


@pytest.fixture(autouse=True)
def _silence_telegram(monkeypatch):
    from dispatch import dispatcher
    sent = []
    monkeypatch.setattr(dispatcher, "send_telegram_message", lambda cid, txt, **k: sent.append(txt) or 1)
    return sent


def _run(rid):
    with Session(db_engine) as s:
        run = s.get(Run, rid)
        tasks = list(s.exec(select(RunTask).where(RunTask.run_id == rid)))
        return run, {t.key: t.status for t in tasks}


def test_mission_creates_run_and_drives_valid_dag(monkeypatch):
    _patch_node(monkeypatch, VALID_DAG)
    snap = asyncio.run(E.run_orchestration("scan BTC into CPI", mode="mission", chat_id=42))
    run, statuses = _run(snap["run_id"])
    assert run.mode == "mission"
    assert run.status == "done"
    assert statuses == {"r": "done", "synth": "done", "verify": "done"}
    # A Job(kind="run") backs the run for observability.
    with Session(db_engine) as s:
        job = s.get(Job, run.job_id)
        assert job is not None and job.kind == "run"
    assert "Final synthesized report." in (snap.get("report") or "")


def test_goal_creates_run_and_drives(monkeypatch):
    _patch_node(monkeypatch, VALID_DAG)
    snap = asyncio.run(E.run_orchestration("ship the integration", mode="goal", chat_id=7))
    run, statuses = _run(snap["run_id"])
    assert run.mode == "goal"
    assert run.status == "done"
    assert statuses.get("r") == "done"


def test_garbage_decompose_degrades_to_working_mission(monkeypatch):
    _patch_node(monkeypatch, "sorry, no json today")
    snap = asyncio.run(E.run_orchestration("read the room", mode="mission", chat_id=1))
    run, statuses = _run(snap["run_id"])
    assert run.status == "done"
    # mission degrade = read node(s) + a synthesize node, all driven to done.
    assert "synth" in statuses and statuses["synth"] == "done"
    assert any(k.startswith("r") for k in statuses)


def test_garbage_decompose_degrades_to_single_goal_node(monkeypatch):
    _patch_node(monkeypatch, "not json")
    snap = asyncio.run(E.run_orchestration("learn rust", mode="goal", chat_id=1))
    run, statuses = _run(snap["run_id"])
    assert run.status == "done"
    assert statuses == {"m0": "done"}  # goal degrade = a single read node
