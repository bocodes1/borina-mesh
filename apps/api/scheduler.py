"""APScheduler wrapper for cron-driven agent runs."""

import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from events import bus, ActivityEvent


def parse_cron(expression: str) -> CronTrigger:
    """Parse a cron expression. Raises ValueError on invalid input."""
    parts = expression.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Cron expression must have 5 fields, got {len(parts)}")
    try:
        return CronTrigger(
            minute=parts[0],
            hour=parts[1],
            day=parts[2],
            month=parts[3],
            day_of_week=parts[4],
        )
    except Exception as e:
        raise ValueError(f"Invalid cron expression: {e}") from e


class SchedulerService:
    """Wraps APScheduler with per-agent schedule management."""

    def __init__(self):
        self._scheduler = AsyncIOScheduler()
        self._schedules: dict[str, str] = {}

    def start(self) -> None:
        if not self._scheduler.running:
            self._scheduler.start()

    def stop(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    def set_schedule(self, agent_id: str, cron_expression: str) -> None:
        trigger = parse_cron(cron_expression)
        job_id = f"agent-{agent_id}"
        if self._scheduler.get_job(job_id):
            self._scheduler.remove_job(job_id)
        self._scheduler.add_job(
            self._run_agent,
            trigger=trigger,
            args=[agent_id],
            id=job_id,
            replace_existing=True,
        )
        self._schedules[agent_id] = cron_expression

    def remove_schedule(self, agent_id: str) -> None:
        job_id = f"agent-{agent_id}"
        if self._scheduler.get_job(job_id):
            self._scheduler.remove_job(job_id)
        self._schedules.pop(agent_id, None)

    def list_schedules(self) -> dict[str, str]:
        return dict(self._schedules)

    def register_defaults(self) -> None:
        """Register the default daily schedules for agents that don't have one yet."""
        # Master schedule list extracted from the Obsidian vault
        # (CO_WORKING_SYSTEM.md, automation/docs/ARCHITECTURE.md,
        # 02-projects/borina-bot.md, 04-resources/skills/self-improvement/CRON-SETUP.md,
        # 02-projects/refined-concept/gmc-cron-setup.md, and memory reference files).
        # One default cron per agent — secondary jobs noted in comments.
        DEFAULT_SCHEDULES = {
            # ── Morning routines ───────────────────────────────────────────
            "ceo":               "0 7 * * *",    # 7 AM daily  — strategic morning briefing (CO_WORKING_SYSTEM.md)
            "ecommerce-scout":   "0 8 * * *",    # 8 AM daily  — KaloData product discovery (borina-bot.md)
            "polymarket-intel":  "0 8 * * *",    # 8 AM daily  — leaderboard/whale + signal synthesis (ARCHITECTURE.md)
            "researcher":        "0 8 * * *",    # 8 AM daily  — morning briefing aggregator (automation_systems.md)
            # ── Ad operations ──────────────────────────────────────────────
            # adset-optimizer also owns the 6 PM GMC analytics report and the
            # 9 AM GMC product-rotation job (gmc-cron-setup.md / ARCHITECTURE.md).
            "adset-optimizer":   "0 17 * * *",   # 5 PM daily  — GMC ad rotation (ARCHITECTURE.md L241)
            # ── Continuous monitoring ──────────────────────────────────────
            # trader also owns: 11 PM daily metrics, 10 PM P&L summary,
            # 2 PM verification check, 4 PM gym accountability ping.
            "trader":            "*/30 * * * *", # Every 30 min — bot health watcher (borina-bot.md)
            "inbox-triage":      "0 */2 * * *",  # Every 2 hours — email/Telegram digest (borina-bot.md)
            # "curator": DISABLED pending wiki v2 redesign — manual /wiki/review only
            # NOTE: weekly memory curator (Sun 10 AM ET = 14 UTC, CRON-SETUP.md)
            # and monthly memory archive (1st of month) are not mapped to a
            # default agent yet — spawn via Memory Curator agent when added.
        }
        from agents.base import registry
        for agent_id, cron in DEFAULT_SCHEDULES.items():
            if not registry.get(agent_id):
                continue
            if agent_id in self._schedules:
                continue
            try:
                self.set_schedule(agent_id, cron)
                print(f"[scheduler] Registered default: {agent_id} @ {cron}")
            except Exception as e:
                print(f"[scheduler] Failed to register {agent_id}: {e}")

        # Wiki daily digest — runs at 8 AM UTC, sends Telegram summary of
        # yesterday's reviewer rejections.
        digest_job_id = "wiki-daily-digest"
        if not self._scheduler.get_job(digest_job_id):
            try:
                trigger = parse_cron("0 8 * * *")
                self._scheduler.add_job(
                    self._run_digest,
                    trigger=trigger,
                    id=digest_job_id,
                    replace_existing=True,
                )
                self._schedules["wiki-daily-digest"] = "0 8 * * *"
                print("[scheduler] Registered default: wiki-daily-digest @ 0 8 * * *")
            except Exception as e:
                print(f"[scheduler] Failed to register wiki digest: {e}")

    async def _run_digest(self) -> None:
        """Run the wiki daily digest."""
        try:
            from wiki_engine.digest import send_daily_digest
            count = await send_daily_digest()
            print(f"[scheduler] wiki digest sent ({count} rejections)")
        except Exception as e:
            print(f"[scheduler] wiki digest error: {e}")

    async def _run_agent(self, agent_id: str) -> None:
        """Execute an agent's scheduled run with full Job/AgentRun persistence."""
        from datetime import datetime
        from sqlmodel import Session
        from agents.base import registry
        from db import engine
        from models import Job, AgentRun, JobStatus

        agent = registry.get(agent_id)
        if not agent:
            await bus.publish(ActivityEvent(
                agent_id=agent_id,
                kind="failed",
                message=f"Scheduled run failed: agent '{agent_id}' not found",
            ))
            return

        prompt = f"Run your scheduled daily task. Current time: {asyncio.get_event_loop().time()}"

        with Session(engine) as session:
            job = Job(
                agent_id=agent_id,
                prompt=f"[scheduled] {prompt}",
                status=JobStatus.RUNNING,
                started_at=datetime.utcnow(),
            )
            session.add(job)
            session.commit()
            session.refresh(job)
            job_id = job.id

        await bus.publish(ActivityEvent(
            agent_id=agent_id,
            kind="scheduled",
            message=f"Scheduled run triggered for {agent.name}",
            job_id=job_id,
        ))

        output_parts = []
        error_msg = None
        try:
            async for chunk in agent.stream(prompt, job_id=job_id):
                if chunk.get("type") == "text":
                    output_parts.append(chunk.get("content", ""))
                elif chunk.get("type") == "error":
                    error_msg = chunk.get("content", "unknown error")
        except Exception as e:
            error_msg = str(e)

        # QA gatekeeper — runs after a successful stream, retries once on REQUEST_RERUN
        qa_verdict = None
        qa_notes = None
        if not error_msg:
            try:
                from agents.qa_director import QADirector, ReviewVerdict
                qa = QADirector()
                full_output = "".join(output_parts)
                review = await qa.review(full_output, prompt)
                qa_verdict = review.verdict.value
                qa_notes = review.notes

                if review.verdict == ReviewVerdict.REQUEST_RERUN:
                    # Retry exactly once with QA feedback appended to prompt
                    output_parts = []
                    error_msg = None
                    retry_prompt = f"{prompt}\n\n[QA rerun: {review.notes}]"
                    try:
                        async for chunk in agent.stream(retry_prompt, job_id=job_id):
                            if chunk.get("type") == "text":
                                output_parts.append(chunk.get("content", ""))
                            elif chunk.get("type") == "error":
                                error_msg = chunk.get("content", "unknown error")
                    except Exception as e:
                        error_msg = str(e)

                    if not error_msg:
                        full_output = "".join(output_parts)
                        review2 = await qa.review(full_output, prompt)
                        qa_verdict = review2.verdict.value
                        qa_notes = review2.notes
            except Exception as e:
                qa_notes = f"QA review failed: {e}"

        with Session(engine) as session:
            final_job = session.get(Job, job_id)
            if final_job:
                final_job.completed_at = datetime.utcnow()
                final_job.qa_verdict = qa_verdict
                final_job.qa_notes = qa_notes
                if error_msg:
                    final_job.status = JobStatus.FAILED
                    final_job.error = error_msg
                else:
                    final_job.status = JobStatus.COMPLETED
                    run = AgentRun(
                        job_id=job_id,
                        agent_id=agent_id,
                        output="".join(output_parts),
                        tokens_used=0,
                        cost_usd=0.0,
                        qa_verdict=qa_verdict,
                        qa_notes=qa_notes,
                    )
                    session.add(run)
                session.add(final_job)
                session.commit()
                if error_msg:
                    try:
                        from artifacts import save_run_output
                        save_run_output(
                            agent_id=agent_id,
                            job_id=job_id,
                            prompt=prompt,
                            output=f"ERROR: {error_msg}\n\nPartial output:\n{''.join(output_parts)}",
                            status="failed",
                        )
                    except Exception:
                        pass
                else:
                    try:
                        from artifacts import save_run_output
                        save_run_output(
                            agent_id=agent_id,
                            job_id=job_id,
                            prompt=prompt,
                            output="".join(output_parts),
                            status="completed",
                        )
                    except Exception as e:
                        print(f"[scheduler] Failed to save run output file: {e}")


# Global singleton
scheduler_service = SchedulerService()
