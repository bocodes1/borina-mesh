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
        DEFAULT_SCHEDULES = {
            "ceo":               "0 7 * * *",
            "ecommerce-scout":   "0 8 * * *",
            "polymarket-intel":  "0 8 * * *",
            "adset-optimizer":   "0 8 * * *",
            "trader":            "*/30 * * * *",
            "inbox-triage":      "0 */2 * * *",
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

    async def _run_agent(self, agent_id: str) -> None:
        """Execute an agent's scheduled run."""
        from agents.base import registry

        agent = registry.get(agent_id)
        if not agent:
            await bus.publish(ActivityEvent(
                agent_id=agent_id,
                kind="failed",
                message=f"Scheduled run failed: agent '{agent_id}' not found",
            ))
            return

        await bus.publish(ActivityEvent(
            agent_id=agent_id,
            kind="scheduled",
            message=f"Scheduled run triggered for {agent.name}",
        ))

        prompt = f"Run your scheduled daily task. Current time: {asyncio.get_event_loop().time()}"
        async for _ in agent.stream(prompt):
            pass


# Global singleton
scheduler_service = SchedulerService()
