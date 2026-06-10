"""Background dispatch worker (spec §3) — makes Telegram dispatch subconscious.

The webhook enqueues a persisted Job (kind=telegram_dispatch, status=queued) and
returns immediately; this worker drains the queue:
- **crash-safe:** queued jobs are DB rows; on startup orphaned `running` jobs are
  re-queued (recover_orphans), so nothing is lost on restart.
- **concurrent:** up to TELEGRAM_MAX_CONCURRENT_JOBS run at once; the rest wait.
- **idempotent:** enqueue is keyed by Telegram update_id, so retried updates don't
  double-run an agent.
- **non-spammy:** one ack up front (sent by the webhook), one optional "still
  working" only past TELEGRAM_PROGRESS_PING_SECONDS, the result when done.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime
from typing import Optional

from sqlmodel import select, func

from db import session_scope
from models import Job, JobStatus

KIND = "telegram_dispatch"


def max_concurrent() -> int:
    try:
        return max(1, int(os.getenv("TELEGRAM_MAX_CONCURRENT_JOBS", "3")))
    except ValueError:
        return 3


def progress_ping_seconds() -> int:
    try:
        return int(os.getenv("TELEGRAM_PROGRESS_PING_SECONDS", "90"))
    except ValueError:
        return 90


# ── persisted-queue primitives (sync; directly unit-testable) ────────────────
def enqueue_job(text: str, agent: str, update_id: Optional[int], chat_id: int) -> Optional[Job]:
    """Create a queued telegram_dispatch job. Returns None if update_id was
    already seen (idempotency) so a retried Telegram update never double-runs."""
    with session_scope() as s:
        if update_id is not None:
            existing = s.exec(select(Job).where(Job.telegram_update_id == update_id)).first()
            if existing is not None:
                return None
        job = Job(
            agent_id=agent,
            prompt=text,
            status=JobStatus.QUEUED,
            kind=KIND,
            telegram_update_id=update_id,
            telegram_chat_id=chat_id,
        )
        s.add(job)
        s.commit()
        s.refresh(job)
        return job


def running_count() -> int:
    with session_scope() as s:
        return int(
            s.exec(
                select(func.count()).select_from(Job).where(Job.kind == KIND, Job.status == JobStatus.RUNNING)
            ).one()
        )


def claim_next() -> Optional[Job]:
    """Atomically move the oldest queued job to running iff under the concurrency
    cap. Returns the claimed job, or None if at capacity / nothing queued."""
    with session_scope() as s:
        running = int(
            s.exec(
                select(func.count()).select_from(Job).where(Job.kind == KIND, Job.status == JobStatus.RUNNING)
            ).one()
        )
        if running >= max_concurrent():
            return None
        job = s.exec(
            select(Job)
            .where(Job.kind == KIND, Job.status == JobStatus.QUEUED)
            .order_by(Job.created_at)
        ).first()
        if job is None:
            return None
        job.status = JobStatus.RUNNING
        job.started_at = datetime.utcnow()
        s.add(job)
        s.commit()
        s.refresh(job)
        return job


def recover_orphans() -> int:
    """On startup, re-queue jobs left `running` by a crash so they aren't lost."""
    with session_scope() as s:
        orphans = s.exec(select(Job).where(Job.kind == KIND, Job.status == JobStatus.RUNNING)).all()
        for job in orphans:
            job.status = JobStatus.QUEUED
            job.started_at = None
            s.add(job)
        s.commit()
        return len(orphans)


def _fail_job(job_id: int, error: str) -> None:
    with session_scope() as s:
        job = s.get(Job, job_id)
        if job:
            job.status = JobStatus.FAILED
            job.completed_at = datetime.utcnow()
            job.error = error[:500]
            s.add(job)
            s.commit()


# ── run a single claimed job ─────────────────────────────────────────────────
async def run_job(job_id: int) -> None:
    from dispatch import dispatcher
    from dispatch.intent import resolve_intent
    from dispatch.telegram_format import format_telegram

    with session_scope() as s:
        job = s.get(Job, job_id)
        if not job:
            return
        chat_id = job.telegram_chat_id
        prompt = job.prompt
        job_agent = job.agent_id

    intent = resolve_intent(prompt)
    if not intent.dispatchable:
        _fail_job(job_id, "intent no longer dispatchable")
        return
    # The webhook already routed this job (thread follow-ups must reach the
    # thread's agent, not what re-resolving the text would pick); the row's
    # agent is authoritative.
    if job_agent:
        intent.agent = job_agent

    ping = asyncio.create_task(_progress_ping(chat_id, intent.agent))
    try:
        await dispatcher._produce_and_reply(intent, chat_id, job_id, datetime.utcnow().isoformat())
    except Exception as exc:  # noqa: BLE001
        _fail_job(job_id, f"{type(exc).__name__}: {exc}")
        if chat_id:
            # Short error to the user — never a stack trace.
            dispatcher.send_telegram_message(
                chat_id, format_telegram(f"Dispatch for {intent.agent} failed. Please retry.")
            )
    finally:
        ping.cancel()


async def _progress_ping(chat_id: Optional[int], agent: str) -> None:
    from dispatch import dispatcher
    from dispatch.telegram_format import format_telegram

    try:
        await asyncio.sleep(progress_ping_seconds())
        if chat_id:
            dispatcher.send_telegram_message(chat_id, format_telegram(f"still working on {agent}, hang tight"))
    except asyncio.CancelledError:
        pass


# ── the drain loop (started in lifespan) ─────────────────────────────────────
class DispatchWorker:
    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._running: set[asyncio.Task] = set()
        self._stop = False

    def start(self) -> None:
        if self._task is not None:
            return
        recover_orphans()
        self._stop = False
        self._task = asyncio.create_task(self._loop())

    def stop(self) -> None:
        self._stop = True
        if self._task:
            self._task.cancel()
            self._task = None

    async def _loop(self) -> None:
        while not self._stop:
            try:
                job = claim_next()
                if job is None:
                    await asyncio.sleep(1.0)
                    continue
                t = asyncio.create_task(run_job(job.id))
                self._running.add(t)
                t.add_done_callback(self._running.discard)
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                print(f"[dispatch-worker] loop error: {exc}")
                await asyncio.sleep(1.0)


worker = DispatchWorker()
