"""APScheduler-based scheduler for recurring Borina Mesh jobs."""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger


def parse_cron(expr: str) -> CronTrigger:
    """Parse a standard 5-field cron expression into an APScheduler CronTrigger."""
    parts = expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Expected 5-field cron expression, got: {expr!r}")
    minute, hour, day, month, day_of_week = parts
    return CronTrigger(
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=day_of_week,
    )


class SchedulerService:
    """Wraps APScheduler and registers default recurring jobs."""

    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler()
        self._schedules: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Job callbacks
    # ------------------------------------------------------------------

    async def _run_morning_brief(self) -> None:
        """Generate the daily morning brief."""
        try:
            from briefs import generate_morning_brief
            from db import engine
            brief = await generate_morning_brief(engine)
            print(f"[scheduler] morning brief generated for {brief.date}")
        except Exception as e:
            print(f"[scheduler] morning brief error: {e}")

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_defaults(self) -> None:
        """Register all default scheduled jobs."""
        brief_job_id = "morning-brief"
        if not self._scheduler.get_job(brief_job_id):
            try:
                trigger = parse_cron("15 7 * * *")
                self._scheduler.add_job(
                    self._run_morning_brief,
                    trigger=trigger,
                    id=brief_job_id,
                    replace_existing=True,
                )
                self._schedules["morning-brief"] = "15 7 * * *"
                print("[scheduler] Registered default: morning-brief @ 15 7 * * *")
            except Exception as e:
                print(f"[scheduler] Failed to register morning brief: {e}")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the scheduler (call during app startup)."""
        self.register_defaults()
        self._scheduler.start()
        print("[scheduler] started")

    def shutdown(self) -> None:
        """Shut down the scheduler gracefully."""
        self._scheduler.shutdown(wait=False)
        print("[scheduler] shut down")

    @property
    def schedules(self) -> dict[str, str]:
        """Return a copy of registered schedule cron expressions."""
        return dict(self._schedules)


# Global singleton
scheduler_service = SchedulerService()
