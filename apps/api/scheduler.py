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

    def _persist_cron(self, agent_id: str, cron: str) -> None:
        """Persist a schedule to AgentConfig so it's inspectable and survives a
        restart (the in-memory APScheduler jobstore does not)."""
        try:
            from db import engine
            from models import AgentConfig
            from sqlmodel import Session
            with Session(engine) as s:
                row = s.get(AgentConfig, agent_id)
                if row is None:
                    row = AgentConfig(agent_id=agent_id)
                row.schedule_cron = cron
                s.add(row)
                s.commit()
        except Exception as e:  # noqa: BLE001
            print(f"[scheduler] could not persist cron for {agent_id}: {e}")

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
        # Honor the fleet roster: only ACTIVE agents get scheduled. Parked and
        # retired agents produce no crons (fixes the cron-noise the user saw).
        try:
            from fleet_roster import active_scheduled_agents
            schedules = active_scheduled_agents(DEFAULT_SCHEDULES)
        except Exception:  # noqa: BLE001
            schedules = DEFAULT_SCHEDULES
        for agent_id, cron in schedules.items():
            if not registry.get(agent_id):
                continue
            if agent_id in self._schedules:
                continue
            try:
                self.set_schedule(agent_id, cron)
                self._persist_cron(agent_id, cron)
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

    async def _run_finance_brief(self) -> None:
        """5am ET finance brief — runs the screen, asks the agent to write up."""
        try:
            from agents.finance_brief import generate_brief
            brief = await generate_brief(use_cache=False)
            status = "ok" if not brief.error else f"error: {brief.error}"
            print(
                f"[scheduler] finance brief {status} "
                f"({brief.duration_seconds}s, {len(brief.markdown)} chars)"
            )
        except Exception as e:
            print(f"[scheduler] finance brief error: {e}")

    async def _run_schedule_daily(self) -> None:
        """Generate the daily brief and write reports/{today}/daily-brief.md."""
        try:
            from schedule_daily import generate_daily_brief
            path = await generate_daily_brief(use_agent=True)
            print(f"[scheduler] schedule_daily wrote {path}")
        except Exception as e:
            print(f"[scheduler] schedule_daily error: {e}")

    def register_schedule_daily(self) -> None:
        """Register the daily brief job at 6am America/New_York (spec §8)."""
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo("America/New_York")
        except Exception:
            tz = None
        job_id = "schedule-daily"
        if self._scheduler.get_job(job_id):
            return
        try:
            trigger = CronTrigger(hour=6, minute=0, timezone=tz) if tz else CronTrigger(hour=11, minute=0)
            self._scheduler.add_job(
                self._run_schedule_daily,
                trigger=trigger,
                id=job_id,
                replace_existing=True,
            )
            self._schedules["schedule-daily"] = "0 6 * * * America/New_York"
            print("[scheduler] Registered default: schedule-daily @ 6am ET")
        except Exception as e:
            print(f"[scheduler] Failed to register schedule_daily: {e}")

    async def _run_planner(self) -> None:
        """Generate the daily plan proposal (NEVER writes the calendar) + send a
        terse Telegram digest. Approval happens later via /daily or Telegram."""
        try:
            from planner import generate_plan_with_agent, plan_digest_text
            summary = await generate_plan_with_agent()
            print(f"[scheduler] planner ({summary['source']}) proposed {summary['task_count']} tasks + {summary['calendar_count']} changes")
            import os
            chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
            if chat:
                from dispatch import dispatcher
                from dispatch.telegram_format import format_telegram
                dispatcher.send_telegram_message(int(chat), format_telegram(plan_digest_text()))
        except Exception as e:
            print(f"[scheduler] planner error: {e}")

    def register_planner(self) -> None:
        """Register the planner job at 6:30am America/New_York."""
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo("America/New_York")
        except Exception:
            tz = None
        job_id = "planner"
        if self._scheduler.get_job(job_id):
            return
        try:
            trigger = CronTrigger(hour=6, minute=30, timezone=tz) if tz else CronTrigger(hour=11, minute=30)
            self._scheduler.add_job(self._run_planner, trigger=trigger, id=job_id, replace_existing=True)
            self._schedules["planner"] = "30 6 * * * America/New_York"
            print("[scheduler] Registered default: planner @ 6:30am ET")
        except Exception as e:
            print(f"[scheduler] Failed to register planner: {e}")

    def register_finance_brief(self) -> None:
        """Register the finance brief job at 5am America/New_York.

        Separate from set_schedule() because that path is a generic
        agent-runner; finance has its own pre-screen step. Uses tz so the
        cron stays at 5am ET regardless of DST.
        """
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo("America/New_York")
        except Exception:
            tz = None
        job_id = "finance-brief"
        if self._scheduler.get_job(job_id):
            return
        try:
            trigger = CronTrigger(hour=5, minute=0, timezone=tz) if tz else CronTrigger(hour=10, minute=0)
            self._scheduler.add_job(
                self._run_finance_brief,
                trigger=trigger,
                id=job_id,
                replace_existing=True,
            )
            self._schedules["finance-brief"] = "0 5 * * * America/New_York"
            print("[scheduler] Registered default: finance-brief @ 5am ET")
        except Exception as e:
            print(f"[scheduler] Failed to register finance brief: {e}")

    async def _run_fleet_health(self) -> None:
        """Weekly: compute fleet-health findings and send the health Card. Does
        NOT auto-park here (auto-park stays a separate opt-in sweep) — surfaces +
        offers buttons. Retire is never automatic."""
        try:
            import os
            from db import engine
            from fleet.health import check_fleet
            from fleet.cards import health_card
            findings = check_fleet(engine)
            chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
            if chat:
                from dispatch.cards import send_card
                send_card(int(chat), health_card(findings))
            print(f"[scheduler] fleet-health: {len(findings)} finding(s)")
        except Exception as e:
            print(f"[scheduler] fleet-health error: {e}")

    def register_fleet_health(self) -> None:
        """Weekly fleet-health report — Mondays 08:00 ET."""
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo("America/New_York")
        except Exception:
            tz = None
        job_id = "fleet-health"
        if self._scheduler.get_job(job_id):
            return
        try:
            trigger = CronTrigger(day_of_week="mon", hour=8, minute=0, timezone=tz) if tz \
                else CronTrigger(day_of_week="mon", hour=13, minute=0)
            self._scheduler.add_job(self._run_fleet_health, trigger=trigger, id=job_id, replace_existing=True)
            self._schedules["fleet-health"] = "0 8 * * mon America/New_York"
            print("[scheduler] Registered default: fleet-health @ Mon 8am ET")
        except Exception as e:
            print(f"[scheduler] Failed to register fleet-health: {e}")

    def _digest_card(self):
        """Weekly outreach digest (read-only): N sent, M replies, K awaiting
        follow-up. Reuses the foundation Card channel. Computes counts straight
        from the staging tables — never sends."""
        from datetime import datetime, timedelta
        from sqlmodel import select
        from db import session_scope
        from models import OutreachItem, OutreachReply
        from dispatch.cards import Card

        week_start = datetime.utcnow() - timedelta(days=7)
        cutoff = datetime.utcnow() - timedelta(days=7)
        with session_scope() as s:
            items = s.exec(select(OutreachItem)).all()
            replies = s.exec(select(OutreachReply)).all()
            sent = sum(1 for it in items if it.sent_at and it.sent_at >= week_start)
            replied = sum(1 for r in replies if r.created_at >= week_start)
            awaiting = sum(
                1 for it in items
                if it.status == "sent" and (it.sent_at or it.created_at) <= cutoff
                and not it.dedup_key.startswith("[followup] ")
            )
            flags = [r.flag for r in replies if r.flag != "neutral" and not r.confirmed]
        lines = [
            f"{sent} sent this week",
            f"{replied} replied",
            f"{awaiting} awaiting follow-up",
        ]
        if flags:
            lines.append("Flagged for your glance: " + ", ".join(sorted(set(flags))))
        return Card(headline="Weekly outreach digest", lines=lines)

    async def _run_apply_weekly(self) -> None:
        """Weekly internship outreach (Phase 1 batch + Phase 2 postings + Phase 3
        sweep). Order: (1) read-only reply detection, (2) stage follow-ups (no
        send), (3) stage the new cold-email + posting batch, (4) post the digest +
        approval cards. NEVER sends/submits — every send stays behind Bo's tap."""
        try:
            import os
            from dispatch import apply as apply_mod
            # Phase 3: read-only reply detection + follow-up staging (no send).
            reply_summary = apply_mod.match_replies()
            followup_summary = await apply_mod.stage_followups()
            # Phase 1 + 2: new cold-email + posting batch (staged, never sent/submitted).
            email_summary = await apply_mod.run_apply("")
            posting_summary = await apply_mod.run_postings("")
            chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
            if chat:
                from routes.telegram import send_apply_cards, send_posting_cards
                from dispatch.cards import send_card
                from dispatch import dispatcher
                from dispatch.telegram_format import format_telegram
                send_card(int(chat), self._digest_card())
                n_email = send_apply_cards(int(chat))
                n_post = send_posting_cards(int(chat))
                staged = email_summary.get("staged", 0) + posting_summary.get("staged", 0)
                dispatcher.send_telegram_message(
                    int(chat),
                    format_telegram(
                        f"Weekly applier: {reply_summary.get('matched', 0)} new repl(ies), "
                        f"staged {followup_summary.get('staged', 0)} follow-up(s) + "
                        f"{staged} new application(s) ({n_email} email, {n_post} posting). "
                        f"Approve each with the buttons."
                    ),
                )
                print(f"[scheduler] apply-weekly: {n_email + n_post} card(s), "
                      f"{reply_summary.get('matched', 0)} repl(ies)")
            else:
                staged = email_summary.get("staged", 0) + posting_summary.get("staged", 0)
                print(f"[scheduler] apply-weekly: staged {staged}, "
                      f"{reply_summary.get('matched', 0)} repl(ies) (no chat configured)")
        except Exception as e:
            print(f"[scheduler] apply-weekly error: {e}")

    def register_apply_weekly(self) -> None:
        """Weekly internship cold-email batch — Mondays 09:00 ET."""
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo("America/New_York")
        except Exception:
            tz = None
        job_id = "apply-weekly"
        if self._scheduler.get_job(job_id):
            return
        try:
            trigger = CronTrigger(day_of_week="mon", hour=9, minute=0, timezone=tz) if tz \
                else CronTrigger(day_of_week="mon", hour=14, minute=0)
            self._scheduler.add_job(self._run_apply_weekly, trigger=trigger, id=job_id, replace_existing=True)
            self._schedules["apply-weekly"] = "0 9 * * mon America/New_York"
            print("[scheduler] Registered default: apply-weekly @ Mon 9am ET")
        except Exception as e:
            print(f"[scheduler] Failed to register apply-weekly: {e}")

    async def _run_operator(self, phase: str) -> None:
        """Run a daily-operator phase (morning/midday/eod). Proposes via Cards;
        never writes the calendar."""
        try:
            from daily_operator import run_phase
            await run_phase(phase)
            print(f"[scheduler] operator {phase} ran")
        except Exception as e:
            print(f"[scheduler] operator {phase} error: {e}")

    def register_operator(self) -> None:
        """Register the daily operator: morning 07:00, midday 13:00, eod 18:00 ET."""
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo("America/New_York")
        except Exception:
            tz = None
        for phase, hour in (("morning", 7), ("midday", 13), ("eod", 18)):
            job_id = f"operator-{phase}"
            if self._scheduler.get_job(job_id):
                continue
            try:
                trigger = CronTrigger(hour=hour, minute=15, timezone=tz) if tz else CronTrigger(hour=hour + 5, minute=15)
                self._scheduler.add_job(
                    self._run_operator, trigger=trigger, args=[phase],
                    id=job_id, replace_existing=True,
                )
                self._schedules[job_id] = f"15 {hour} * * * America/New_York"
                print(f"[scheduler] Registered default: operator-{phase} @ {hour}:15 ET")
            except Exception as e:
                print(f"[scheduler] Failed to register operator-{phase}: {e}")

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

        prompt = f"Run your scheduled daily task. Now: {datetime.utcnow().isoformat(timespec='seconds')}Z"

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

        from agents.runner_v2 import run_agent_task, AGENT_REGISTRY
        SCHEDULER_TO_RUNNER = {
            "ceo": "ceo",
            "trader": "trader",
            "researcher": "researcher",
            "ecommerce-scout": "scout",
            "polymarket-intel": "polymarket",
            "adset-optimizer": "adset",
            "inbox-triage": "inbox",
        }
        runner_id = SCHEDULER_TO_RUNNER.get(agent_id)

        output_parts = []
        error_msg = None
        try:
            if runner_id and runner_id in AGENT_REGISTRY:
                # Persistent tmux session path (runner_v2).
                result = await run_agent_task(runner_id, prompt)
                if result.ok:
                    output_parts.append(result.output)
                else:
                    error_msg = result.error
            else:
                # Fallback to legacy SDK streaming for unmapped agents.
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
                        if runner_id and runner_id in AGENT_REGISTRY:
                            retry_result = await run_agent_task(runner_id, retry_prompt)
                            if retry_result.ok:
                                output_parts.append(retry_result.output)
                            else:
                                error_msg = retry_result.error
                        else:
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
