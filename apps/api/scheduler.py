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

    @staticmethod
    def _roster_active(agent_id: str) -> bool:
        """Roster gate for the dedicated register_* methods (§A4). Mirrors how
        register_defaults uses active_scheduled_agents: only ACTIVE agents
        schedule. Unknown ids default to active (fail-open for new infra jobs).
        Any error fails open so a roster glitch never silently kills a brief."""
        try:
            from fleet_roster import get_state, ACTIVE
            return get_state(agent_id) == ACTIVE
        except Exception:  # noqa: BLE001
            return True

    def register_defaults(self) -> None:
        """Register the default daily schedules for agents that don't have one yet."""
        # Master schedule list extracted from the Obsidian vault
        # (CO_WORKING_SYSTEM.md, automation/docs/ARCHITECTURE.md,
        # 02-projects/borina-bot.md, 04-resources/skills/self-improvement/CRON-SETUP.md,
        # 02-projects/refined-concept/gmc-cron-setup.md, and memory reference files).
        # One default cron per agent — secondary jobs noted in comments.
        DEFAULT_SCHEDULES = {
            # ── Morning routines ───────────────────────────────────────────
            # NOTE (efficiency overhaul §A3): the `ceo` 7am and `researcher` 8am
            # crons were REMOVED — they produced redundant morning narratives for
            # the same day. The single surviving morning brief is the 6:30 planner
            # (register_planner), which sends the Telegram digest Bo reads.
            "ecommerce-scout":   "0 8 * * *",    # 8 AM daily  — KaloData product discovery (borina-bot.md)
            # ── Ad operations ──────────────────────────────────────────────
            # adset-optimizer also owns the 6 PM GMC analytics report and the
            # 9 AM GMC product-rotation job (gmc-cron-setup.md / ARCHITECTURE.md).
            "adset-optimizer":   "0 17 * * *",   # 5 PM daily  — GMC ad rotation (ARCHITECTURE.md L241)
            # ── Continuous monitoring ──────────────────────────────────────
            # NOTE (efficiency overhaul §A1): the `trader` */30 LLM cron was
            # REMOVED — it spawned an Opus-reviewed agent every 30 min just to
            # watch a bot. Replaced by the cheap non-LLM `register_trader_health`
            # uptime ping below, which only messages Bo on failure.
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
        import os
        for agent_id, cron in schedules.items():
            if not registry.get(agent_id):
                continue
            if agent_id == "inbox-triage" and not os.getenv("MICROSOFT_OAUTH_CLIENT_ID"):
                print("[scheduler] inbox-triage cron skipped — Microsoft OAuth not configured")
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

    async def _run_trader_health(self) -> None:
        """Cheap NON-LLM uptime ping for the trading bot (replaces the old */30
        Opus-reviewed `trader` agent cron, §A1). Hits the bot's health endpoint
        and ONLY messages Bo on failure — a healthy bot stays silent (no cost, no
        noise). No-ops when no health URL is configured, so it's inert in dev/CI."""
        import os
        url = os.getenv("TRADER_BOT_HEALTH_URL", "").strip()
        if not url:
            return  # nothing to watch — stay silent
        ok = False
        detail = ""
        try:
            import httpx
            resp = httpx.get(url, timeout=10.0)
            ok = resp.status_code == 200
            detail = f"HTTP {resp.status_code}"
        except Exception as e:  # noqa: BLE001
            detail = str(e)
        if ok:
            return  # healthy — no message
        try:
            chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
            if chat:
                from dispatch import dispatcher
                from dispatch.telegram_format import format_telegram
                dispatcher.send_telegram_message(
                    int(chat),
                    format_telegram(f"⚠️ Trading bot health check failed: {detail}"),
                )
            print(f"[scheduler] trader-health: DOWN ({detail})")
        except Exception as e:  # noqa: BLE001
            print(f"[scheduler] trader-health alert error: {e}")

    def register_trader_health(self) -> None:
        """Register the non-LLM trader uptime ping every 10 minutes (§A1)."""
        job_id = "trader-health"
        if self._scheduler.get_job(job_id):
            return
        try:
            trigger = parse_cron("*/10 * * * *")
            self._scheduler.add_job(
                self._run_trader_health,
                trigger=trigger,
                id=job_id,
                replace_existing=True,
            )
            self._schedules["trader-health"] = "*/10 * * * *"
            print("[scheduler] Registered default: trader-health (non-LLM) @ */10")
        except Exception as e:
            print(f"[scheduler] Failed to register trader-health: {e}")

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
        """Register the planner job at 6:30am America/New_York — the single
        consolidated morning brief (§A3). Honors the fleet roster (§A4): if
        `planner` is parked/retired it does not schedule."""
        if not self._roster_active("planner"):
            print("[scheduler] planner not active in roster — skipping schedule")
            return
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
        if not self._roster_active("finance"):
            print("[scheduler] finance not active in roster — skipping schedule")
            return
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
        """Register the daily operator: midday 13:00, eod 18:00 ET.

        The `morning` phase was REMOVED (§A3) — it byte-for-byte duplicated the
        6:30 planner brief. Honors the fleet roster (§A4): skips if `operator`
        is parked/retired."""
        if not self._roster_active("operator"):
            print("[scheduler] operator not active in roster — skipping schedule")
            return
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo("America/New_York")
        except Exception:
            tz = None
        for phase, hour in (("midday", 13), ("eod", 18)):
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
            "adset-optimizer": "adset",
            "inbox-triage": "inbox",
        }
        runner_id = SCHEDULER_TO_RUNNER.get(agent_id)

        # ── Job-contract path (grounded task + clean output + skip-if-no-signal) ──
        from agents import contracts as _contracts
        from agents.context_pack import build_context_pack
        task_spec = _contracts.load_task_spec(runner_id) if runner_id else None

        output_parts = []
        error_msg = None
        try:
            if runner_id in _contracts.CONTRACTED and task_spec:
                last = _contracts.last_artifact_text(agent_id)
                pack = build_context_pack(agent_id, query=agent.name, data="",
                                          last_artifact=last)
                if _contracts.should_skip(runner_id, pack.signal_hash):
                    # No meaningful change — persist a one-line artifact, zero LLM.
                    output_parts.append("NO CHANGE")
                else:
                    from dispatch.answer import run_agent_for_answer
                    run_prompt = (
                        f"{task_spec}\n\nCONTEXT:\n{pack.text}\n\n"
                        "Do the job above using only this context. Output in the format the "
                        "task specifies. If the context shows nothing new, reply exactly: NO CHANGE."
                    )
                    body = await run_agent_for_answer(runner_id, run_prompt, job_id)
                    output_parts.append(body)
                    _contracts.write_last_signal(runner_id, pack.signal_hash)
            elif runner_id and runner_id in AGENT_REGISTRY:
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

        # NOTE (efficiency overhaul §A2): the post-run QADirector.review() Opus
        # call was REMOVED from the scheduled/cron path. It was the entire
        # recurring-Opus cost and added no operator-visible value for digest/health
        # runs. Scheduled runs no longer carry a QA verdict. (Interactive
        # dashboard-chat QA in chat.py is untouched and out of scope here.)
        qa_verdict = None
        qa_notes = None

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
