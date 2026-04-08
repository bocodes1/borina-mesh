import pytest
from scheduler import SchedulerService, parse_cron


def test_parse_cron_valid():
    trigger = parse_cron("0 8 * * *")
    assert trigger is not None


def test_parse_cron_invalid():
    with pytest.raises(ValueError):
        parse_cron("not a cron")


@pytest.mark.asyncio
async def test_scheduler_register_and_list(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    from db import init_db
    init_db()

    service = SchedulerService()
    service.start()
    try:
        service.set_schedule("ceo", "0 8 * * *")
        schedules = service.list_schedules()
        assert "ceo" in schedules
        assert schedules["ceo"] == "0 8 * * *"

        service.remove_schedule("ceo")
        assert "ceo" not in service.list_schedules()
    finally:
        service.stop()
