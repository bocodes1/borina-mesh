"""Weekly cold-email cron (Phase 1): registers apply-weekly @ Mon 9am ET,
idempotently. Mirrors register_fleet_health. The handler never sends — it stages
+ posts cards (send stays behind Bo's approval tap)."""
import pytest

from scheduler import SchedulerService


@pytest.mark.asyncio
async def test_register_apply_weekly_is_idempotent():
    # async so AsyncIOScheduler.start() has a running event loop (matches the
    # rest of test_scheduler.py, which exercises the service inside the loop).
    svc = SchedulerService()
    svc.start()
    try:
        svc.register_apply_weekly()
        svc.register_apply_weekly()  # second call no-ops
        job = svc._scheduler.get_job("apply-weekly")
        assert job is not None
        assert svc.list_schedules().get("apply-weekly") == "0 9 * * mon America/New_York"
    finally:
        svc.stop()


@pytest.mark.asyncio
async def test_run_apply_weekly_stages_without_sending(monkeypatch):
    from dispatch import apply as ap
    from integrations import outlook
    from integrations.base import ok

    sent = []
    monkeypatch.setattr(outlook, "send_mail",
                        lambda *a, **k: sent.append(1) or ok("outlook", {"id": "x", "via": "graph"}))

    async def fake_run(criteria="", chat_id=None):
        return {"staged": 2, "dropped": 0, "item_ids": [1, 2], "reasons": []}

    monkeypatch.setattr(ap, "run_apply", fake_run)
    monkeypatch.setattr(ap, "get_proposed", lambda: [])
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    svc = SchedulerService()
    await svc._run_apply_weekly()  # no chat configured → no cards, but no error
    assert sent == []  # the cron never sends
