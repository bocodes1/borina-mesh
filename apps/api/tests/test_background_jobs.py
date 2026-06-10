"""Background dispatch queue (spec §3)."""
import asyncio

import pytest
from fastapi.testclient import TestClient

from main import app
import routes.telegram as tg
from dispatch import dispatcher, worker
from dispatch.worker import enqueue_job, claim_next, recover_orphans, run_job
from db import session_scope
from models import Job, JobStatus

client = TestClient(app)
SECRET = "s3cr3t"
BO = 6452258223
HEADERS = {"X-Telegram-Bot-Api-Secret-Token": SECRET}


@pytest.fixture(autouse=True)
def _mocks(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", str(BO))
    monkeypatch.setattr(dispatcher, "send_telegram_message", lambda *a, **k: None)
    monkeypatch.setattr(dispatcher, "send_telegram_document", lambda *a, **k: None)
    monkeypatch.setattr(dispatcher, "render_markdown_pdf", lambda md, out: (out.parent.mkdir(parents=True, exist_ok=True), out.write_bytes(b"%PDF"), out)[-1])
    # Isolate the queue from cross-test state so claim_next() is deterministic.
    from sqlmodel import select
    with session_scope() as s:
        for j in s.exec(select(Job).where(Job.kind == "telegram_dispatch")).all():
            s.delete(j)
        s.commit()
    yield


def _status(job_id: int):
    with session_scope() as s:
        return s.get(Job, job_id).status


def test_webhook_returns_200_without_awaiting_run(monkeypatch):
    ran = []
    async def fake_run_agent(agent, prompt):
        ran.append(agent)
        return "# R\n\nok"
    monkeypatch.setattr(dispatcher, "run_agent", fake_run_agent)

    r = client.post(
        "/api/telegram/webhook",
        json={"update_id": 100, "message": {"chat": {"id": BO}, "text": "research AI chips"}},
        headers=HEADERS,
    )
    assert r.status_code == 200 and r.json()["status"] == "dispatched"
    # The agent did NOT run during the request — it's only queued.
    assert ran == []
    with session_scope() as s:
        job = s.exec(__import__("sqlmodel").select(Job).where(Job.telegram_update_id == 100)).first()
    assert job is not None and job.status == JobStatus.QUEUED


def test_job_transitions_queued_running_done(monkeypatch):
    async def fake_run_agent(agent, prompt):
        return "# Report\n\nAAPL steady."
    monkeypatch.setattr(dispatcher, "run_agent", fake_run_agent)

    job = enqueue_job("research nvidia", "researcher", 200, BO)
    assert job.status == JobStatus.QUEUED

    claimed = claim_next()
    assert claimed.id == job.id and claimed.status == JobStatus.RUNNING

    asyncio.run(run_job(job.id))
    assert _status(job.id) == JobStatus.COMPLETED


def test_concurrency_cap_respected(monkeypatch):
    monkeypatch.setenv("TELEGRAM_MAX_CONCURRENT_JOBS", "2")
    for i in range(3):
        enqueue_job(f"research topic {i}", "researcher", 300 + i, BO)

    a = claim_next()
    b = claim_next()
    c = claim_next()  # at cap (2 running) → must refuse
    assert a is not None and b is not None
    assert c is None


def test_queued_job_survives_simulated_restart(monkeypatch):
    job = enqueue_job("research macro", "researcher", 400, BO)
    # claim → running, then a crash leaves it running
    claim_next_job = claim_next()
    assert claim_next_job is not None
    assert _status(job.id) == JobStatus.RUNNING

    # simulated restart: orphan recovery re-queues it (not lost)
    recovered = recover_orphans()
    assert recovered >= 1
    assert _status(job.id) == JobStatus.QUEUED


def test_duplicate_update_id_runs_once(monkeypatch):
    first = enqueue_job("research X", "researcher", 500, BO)
    dup = enqueue_job("research X", "researcher", 500, BO)
    assert first is not None
    assert dup is None  # idempotent: same update_id → not re-enqueued
    with session_scope() as s:
        from sqlmodel import select, func
        count = s.exec(select(func.count()).select_from(Job).where(Job.telegram_update_id == 500)).one()
    assert int(count) == 1


def test_run_job_honors_job_agent_over_reresolution(monkeypatch):
    """A queued job's agent_id (set by the webhook/thread lookup) wins over
    what re-resolving the prompt text would pick."""
    import asyncio
    from dispatch import worker, dispatcher
    from dispatch.worker import enqueue_job

    seen = {}

    async def fake_produce(intent, chat_id, job_id, requested_at):
        seen["agent"] = intent.agent

    monkeypatch.setattr(dispatcher, "_produce_and_reply", fake_produce)
    monkeypatch.setattr(dispatcher, "send_telegram_message", lambda *a, **k: None)

    # "what changed overnight" re-resolves to researcher (fallback) — the job
    # row says trader (thread follow-up), and trader must win.
    job = enqueue_job("what changed overnight", "trader", 9001, 6452258223)
    asyncio.run(worker.run_job(job.id))
    assert seen["agent"] == "trader"
