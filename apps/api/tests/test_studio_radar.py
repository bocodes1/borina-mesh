"""Scheduled radar → brief cards (M5): dedupe by ticker, Big swings in one card,
a failure said once, quiet hours and the off switch."""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from dispatch import studio_radar
from dispatch import studio_tokens as tokens
from tests.fakes.studio import buttons, clean_tables, install

NY = ZoneInfo("America/New_York")
NOON = datetime(2026, 10, 9, 12, 0, tzinfo=NY)
REL = "radar/briefs/2026-10-09-3.json"


def brief(rank, ticker, name, swing=False):
    return {"id": f"2026-10-09-3#{'swing-1' if swing else rank}", "rank": None if swing else rank, "name": name,
            "ticker": ticker, "lane": "C" if swing else "A", "pitch": f"{name}, the working version.",
            "moneyLoop": "Fees buy back the token.", "attention": "A live board anyone can watch.",
            "larpSource": "A fictional larp - larp - nothing behind the site.", "bigSwing": swing}


@pytest.fixture
def studio(monkeypatch, tmp_path):
    env = install(monkeypatch, tmp_path)
    (tmp_path / "radar" / "briefs").mkdir(parents=True)

    def write(*briefs):
        doc = {"version": 1, "run": "radar/runs/20261009-1600", "date": "2026-10-09",
               "markdown": "radar/briefs/2026-10-09-3.md", "briefs": list(briefs)}
        (tmp_path / REL).write_text(json.dumps(doc))

    env.write = write
    env.cli.reply("radar", 0, f"claude: success, 37 turns\nBRIEFS {REL}\n")
    yield env
    clean_tables()


def test_each_new_brief_gets_build_and_skip_and_swings_share_one_card(studio):
    studio.write(brief(2, "SAMPLEB", "Sample Board"), brief(1, "SAMPLE", "Sample Desk"),
                 brief(None, "SWING", "Sample Swing", swing=True))
    assert studio_radar.run_radar_job(now=NOON) == {"status": "ok", "sent": 2, "swings": 1}
    assert studio.cli.calls == [["radar", "--headless"]]
    first, second, swings = studio.sent
    assert "#1 Sample Desk ($SAMPLE)" in first["text"] and "#2 Sample Board ($SAMPLEB)" in second["text"]
    assert [label for label, _ in buttons(first)] == ["Build", "Skip"]
    build = tokens.peek(buttons(first)[0][1])
    assert build["kind"] == "build" and build["payload"] == {"briefsFile": REL, "briefId": "2026-10-09-3#1", "ticker": "SAMPLE"}
    assert "Big swings" in swings["text"] and [label for label, _ in buttons(swings)] == ["Build $SWING"]


def test_a_ticker_is_carded_once_across_runs(studio):
    studio.write(brief(1, "SAMPLE", "Sample Desk"))
    studio_radar.run_radar_job(now=NOON)
    assert studio_radar.run_radar_job(now=NOON) == {"status": "ok", "sent": 0, "swings": 0}
    assert len(studio.sent) == 1


def test_a_failure_is_said_once_until_a_run_works_again(studio):
    studio.cli.reply("radar", 1, "FAIL egress port 18788 is busy (an interactive radar may be running)\n")
    assert studio_radar.run_radar_job(now=NOON)["status"] == "failed"
    studio_radar.run_radar_job(now=NOON)
    assert len(studio.sent) == 1 and "egress port 18788 is busy" in studio.sent[0]["text"]


def test_a_briefs_path_outside_radar_briefs_is_never_read(studio, tmp_path):
    (tmp_path / "secret.json").write_text(json.dumps({"briefs": [brief(1, "SAMPLE", "Sample Desk")]}))
    studio.cli.reply("radar", 0, "BRIEFS radar/briefs/../../secret.json\n")
    assert studio_radar.run_radar_job(now=NOON)["status"] == "failed"
    assert all("Sample Desk" not in m["text"] for m in studio.sent)


def test_a_brief_bo_skipped_on_the_dashboard_is_not_carded(studio, tmp_path):
    studio.write(brief(1, "SAMPLE", "Sample Desk"), brief(2, "SAMPLEB", "Sample Board"))
    (tmp_path / "radar" / "briefs" / ".skipped.json").write_text(json.dumps({"skipped": ["2026-10-09-3#1"]}))
    assert studio_radar.run_radar_job(now=NOON)["sent"] == 1
    assert "Sample Board" in studio.sent[0]["text"]


def test_briefs_that_break_the_contract_are_skipped(studio):
    studio.write(brief(1, "sample", "Sample Desk"), brief(2, "SAMPLEB", "Sample Board"))
    assert studio_radar.run_radar_job(now=NOON)["sent"] == 1


def test_quiet_hours_and_the_off_switch_spend_nothing(studio, monkeypatch):
    studio.write(brief(1, "SAMPLE", "Sample Desk"))
    monkeypatch.setenv("STUDIO_QUIET_HOURS", "23-7")
    night = datetime(2026, 10, 9, 2, 0, tzinfo=NY)
    assert studio_radar.run_radar_job(now=night)["status"] == "quiet"
    assert studio_radar.run_radar_job(now=night, force=True)["status"] == "ok"
    monkeypatch.setenv("STUDIO_ENABLED", "")
    assert studio_radar.run_radar_job(now=NOON)["status"] == "disabled"
    assert studio.cli.calls == [["radar", "--headless"]]


@pytest.mark.parametrize("raw,hours", [("", 6), ("4", 4), ("0", 0), ("5", 6), ("x", 6), ("24", 24)])
def test_the_cadence_setting(monkeypatch, raw, hours):
    monkeypatch.setenv("STUDIO_RADAR_EVERY_H", raw)
    assert studio_radar.every_hours() == hours


def test_register_studio_radar_follows_the_settings(monkeypatch):
    from scheduler import SchedulerService

    monkeypatch.setenv("STUDIO_ENABLED", "1")
    monkeypatch.setenv("STUDIO_RADAR_EVERY_H", "4")
    on = SchedulerService()
    on.register_studio_radar()
    assert on.list_schedules()["studio-radar"] == "7 */4 * * * America/New_York"
    monkeypatch.setenv("STUDIO_ENABLED", "")
    off = SchedulerService()
    off.register_studio_radar()
    assert "studio-radar" not in off.list_schedules()


def test_the_scheduled_radar_runs_detached(monkeypatch):
    import asyncio

    from dispatch import studio_runner
    from scheduler import SchedulerService

    started = []
    monkeypatch.setattr(studio_runner, "spawn_radar", lambda force=False: started.append(force) or 1)
    monkeypatch.setattr(studio_radar, "run_radar_job", lambda *a, **k: pytest.fail("the API must not hold the radar"))
    asyncio.run(SchedulerService()._run_studio_radar())
    assert started == [False]


def test_a_radar_bo_asked_for_always_reports_its_outcome(studio):
    studio.cli.reply("radar", 1, "FAIL egress port 18788 is busy (an interactive radar may be running)\n")
    studio_radar.run_radar_job(now=NOON)
    studio_radar.run_radar_job(now=NOON, force=True)
    assert len(studio.sent) == 2
    studio.write(brief(1, "SAMPLE", "Sample Desk"))
    studio.cli.reply("radar", 0, f"BRIEFS {REL}\n")
    studio_radar.run_radar_job(now=NOON)
    n = len(studio.sent)
    studio_radar.run_radar_job(now=NOON, force=True)
    assert len(studio.sent) == n + 1 and "no new briefs" in studio.sent[-1]["text"]
