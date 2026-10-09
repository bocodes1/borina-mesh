"""/studio (M5): projects, waiting stops, the last radar run, and a radar run on demand."""
import json
from pathlib import Path

import pytest

import routes.telegram as tg
from dispatch import studio, studio_radar
from pipeline_status import record_pipeline_run
from tests.fakes.studio import BO, clean_tables, install


@pytest.fixture
def env(monkeypatch, tmp_path):
    e = install(monkeypatch, tmp_path)
    yield e
    clean_tables()


def _cmd(text):
    return tg.process_update({"update_id": 5, "message": {"chat": {"id": BO}, "text": text}})


def test_studio_lists_projects_stops_and_the_last_radar(env):
    env.cli.reply("status", 0, json.dumps({"projects": [{"slug": "sample-desk", "name": "Sample Desk", "ticker": "SAMPLE", "stage": "look"}]}) + "\n")
    env.cli.reply("stops", 0, json.dumps({"stops": [{"id": "look-1", "slug": "sample-desk"}]}) + "\n")
    record_pipeline_run("studio-radar", True, "2 new, 1 swings")
    assert _cmd("/studio")["status"] == "studio"
    text = env.sent[-1]["text"]
    assert "Sample Desk ($SAMPLE) · sample-desk · look · 1 stop waiting" in text
    assert "Radar: last run" in text and "2 new, 1 swings" in text


def test_studio_when_the_cli_is_down(env):
    env.cli.reply("status", 1, "Error: boom\n")
    _cmd("/studio")
    assert "isn't answering" in env.sent[-1]["text"]


def test_studio_radar_runs_one_now(env, monkeypatch):
    monkeypatch.setattr(studio_radar, "run_radar_job", lambda *a, **k: pytest.fail("the API must not hold the radar"))
    assert _cmd("/studio radar")["status"] == "studio_radar"
    assert env.radars == [True] and "Radar started" in env.sent[0]["text"]


def test_studio_radar_says_when_the_studio_is_off(env, monkeypatch):
    monkeypatch.setenv("STUDIO_ENABLED", "")
    _cmd("/studio radar")
    assert env.radars == [] and "STUDIO_ENABLED" in env.sent[-1]["text"]


def test_studio_is_in_the_command_menu_and_the_help():
    assert {"command": "studio", "description": "Launch Studio: projects, stops, radar now"} in tg.COMMANDS
    assert "/studio" in tg._HELP_TEXT


def test_startup_registers_both_studio_jobs():
    main_py = (Path(__file__).resolve().parents[1] / "main.py").read_text()
    assert "scheduler_service.register_studio_radar()" in main_py
    assert "scheduler_service.register_studio_stops()" in main_py
