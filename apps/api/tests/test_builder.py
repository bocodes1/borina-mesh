"""Autonomous builder: 'build: <task>' from Telegram spawns a detached
headless Claude Code run in a git worktree; ships only after independently
verifying the suites; messages Bo ONLY when stuck; a reply resumes or aborts.

These tests cover the control plane (start/reply/evaluate/orphans) — the
headless claude run itself is integration-tested live."""
import os
import subprocess
from types import SimpleNamespace

import pytest
from sqlmodel import Session, select

import models  # noqa: F401 — register tables before conftest's init_db runs
from main import app  # noqa: F401 — registers the agent roster
import routes.telegram as tg
from db import engine, session_scope
from dispatch import builder, dispatcher
from models import Job, JobStatus

BO = 6452258223


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", str(BO))
    monkeypatch.setattr(dispatcher, "send_telegram_message", lambda *a, **k: 1)
    monkeypatch.setattr(builder, "_spawn", lambda job_id, resume=False: None)
    yield
    with session_scope() as s:
        for j in s.exec(select(Job).where(Job.kind == "builder")).all():
            s.delete(j)
        s.commit()


def _msg(update_id, text):
    return {"update_id": update_id, "message": {"chat": {"id": BO}, "text": text}}


def test_build_command_starts_builder(monkeypatch):
    sent = []
    monkeypatch.setattr(dispatcher, "send_telegram_message",
                        lambda cid, txt: sent.append(txt) or 1)
    res = tg.process_update(_msg(900, "build: add a /ping endpoint that returns pong"))
    assert res["status"] == "build_started"
    with Session(engine) as s:
        job = s.get(Job, res["job_id"])
    assert job.kind == "builder" and job.status == JobStatus.RUNNING
    assert job.worker_branch == f"build/job{job.id}"
    assert "add a /ping endpoint" in job.prompt
    assert any("only ping you if" in t for t in sent)


def test_build_from_non_allowed_ignored(monkeypatch):
    update = {"update_id": 901, "message": {"chat": {"id": 999}, "text": "build: evil"}}
    assert tg.process_update(update)["status"] == "ignored"


def test_builder_reply_abort_fails_job(monkeypatch):
    job_id = builder.start_build("some task", BO)
    thread = SimpleNamespace(agent_id="builder", job_id=job_id, prompt="some task")
    res = builder.handle_builder_reply(thread, "abort", BO)
    assert res["status"] == "build_aborted"
    with Session(engine) as s:
        assert s.get(Job, job_id).status == JobStatus.FAILED


def test_builder_reply_guidance_resumes(monkeypatch, tmp_path):
    spawns = []
    monkeypatch.setattr(builder, "_spawn",
                        lambda job_id, resume=False: spawns.append((job_id, resume)))
    monkeypatch.setattr(builder, "BUILDS", tmp_path)
    job_id = builder.start_build("some task", BO)
    wt = tmp_path / f"job{job_id}"
    wt.mkdir()
    (wt / "BLOCKED.md").write_text("which port?")
    thread = SimpleNamespace(agent_id="builder", job_id=job_id, prompt="some task")
    res = builder.handle_builder_reply(thread, "use port 9999", BO)
    assert res["status"] == "build_resumed"
    assert "use port 9999" in (wt / "GUIDANCE.md").read_text()
    assert not (wt / "BLOCKED.md").exists()
    assert (job_id, True) in spawns


def test_reply_to_builder_thread_routes_to_builder(monkeypatch):
    handled = {}
    monkeypatch.setattr(builder, "handle_builder_reply",
                        lambda thread, text, chat_id: handled.update(t=text) or
                        {"ok": True, "status": "build_resumed"})
    dispatcher._record_thread(BO, 650, "builder", 77, "build: x")
    update = {"update_id": 902,
              "message": {"chat": {"id": BO}, "text": "use redis",
                          "reply_to_message": {"message_id": 650}}}
    res = tg.process_update(update)
    assert res["status"] == "build_resumed"
    assert handled["t"] == "use redis"


# ── worktree evaluation (real tiny git repos) ────────────────────────────────

def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-b", "main")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "t")
    (r / "a.txt").write_text("hello")
    _git(r, "add", ".")
    _git(r, "commit", "-m", "init")
    return r


def test_evaluate_blocked(repo, tmp_path):
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "-b", "build/x", str(wt), "main")
    (wt / "BLOCKED.md").write_text("need a decision on X")
    state, detail = builder.evaluate_worktree(wt, repo)
    assert state == "stuck" and "decision on X" in detail


def test_evaluate_nochange(repo, tmp_path):
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "-b", "build/x", str(wt), "main")
    assert builder.evaluate_worktree(wt, repo)[0] == "nochange"


def test_evaluate_uncommitted_is_stuck(repo, tmp_path):
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "-b", "build/x", str(wt), "main")
    (wt / "b.txt").write_text("dirty")
    state, detail = builder.evaluate_worktree(wt, repo)
    assert state == "stuck"


def test_evaluate_ready(repo, tmp_path):
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "-b", "build/x", str(wt), "main")
    (wt / "b.txt").write_text("new")
    _git(wt, "add", ".")
    _git(wt, "commit", "-m", "feat: b")
    assert builder.evaluate_worktree(wt, repo)[0] == "ready"


# ── orphan recovery must not kill live builders ──────────────────────────────

def test_orphan_recovery_spares_live_builder():
    from stats_helper import fail_orphaned_running_jobs

    with session_scope() as s:
        alive = Job(agent_id="builder", prompt="x", status=JobStatus.RUNNING,
                    kind="builder", worker_pid=os.getpid())
        dead = Job(agent_id="builder", prompt="y", status=JobStatus.RUNNING,
                   kind="builder", worker_pid=99999999)
        s.add(alive); s.add(dead); s.commit()
        s.refresh(alive); s.refresh(dead)
        alive_id, dead_id = alive.id, dead.id

    fail_orphaned_running_jobs(engine)
    with Session(engine) as s:
        assert s.get(Job, alive_id).status == JobStatus.RUNNING
        assert s.get(Job, dead_id).status == JobStatus.FAILED


def test_status_includes_builder_jobs(monkeypatch):
    with session_scope() as s:
        j = Job(agent_id="builder", prompt="build: add ping", status=JobStatus.RUNNING,
                kind="builder", worker_pid=os.getpid())
        s.add(j); s.commit()
    text = tg._fleet_status_text()
    assert "builder" in text and "add ping" in text
