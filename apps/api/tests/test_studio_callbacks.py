"""Build / Skip / Retry taps (M5): fail-closed, single use, no traceback in chat."""
import json

import pytest

from db import session_scope
from dispatch import studio_tokens as tokens
from models import StudioBrief
from tests.fakes.studio import clean_tables, install, tap

BRIEFS = "radar/briefs/2026-10-09-3.json"


@pytest.fixture
def studio(monkeypatch, tmp_path):
    env = install(monkeypatch, tmp_path)
    yield env
    clean_tables()


def _build_token() -> str:
    with session_scope() as s:
        s.add(StudioBrief(ticker="SAMPLE", briefs_file=BRIEFS, brief_id="2026-10-09-3#1", name="Sample Desk"))
        s.commit()
    return tokens.mint("build", {"briefsFile": BRIEFS, "briefId": "2026-10-09-3#1", "ticker": "SAMPLE"})


def test_build_creates_the_project_and_starts_a_detached_run(studio):
    studio.cli.reply("new", 0, "PROJECT sample-desk\n")
    res = tap(_build_token())
    assert res["status"] == "studio_build" and res["toast"] == "Started"
    assert studio.cli.calls == [["new", "--brief", f"{BRIEFS}#2026-10-09-3#1"]]
    assert studio.spawned == ["sample-desk"]
    with session_scope() as s:
        row = s.get(StudioBrief, "SAMPLE")
        assert row.status == "building" and row.slug == "sample-desk"


def test_a_second_build_tap_does_nothing(studio):
    studio.cli.reply("new", 0, "PROJECT sample-desk\n")
    data = _build_token()
    tap(data)
    assert tap(data)["toast"] == "Already started"
    assert studio.cli.subcommands() == ["new"] and studio.spawned == ["sample-desk"]


def test_a_failed_new_can_be_tapped_again_and_never_shows_a_trace(studio):
    studio.cli.reply("new", 1, "Error: boom\n    at main (/Users/clawd/dev/launch-studio/scripts/studio.ts:40:9)\n")
    data = _build_token()
    assert tap(data)["status"] == "studio_build_failed"
    assert "studio.ts" not in studio.sent[-1]["text"] and studio.spawned == []
    studio.cli.reply("new", 0, "PROJECT sample-desk\n")
    assert tap(data)["status"] == "studio_build"


def test_skip_marks_the_brief_tells_the_dashboard_and_runs_nothing(studio, tmp_path):
    briefs_dir = tmp_path / "radar" / "briefs"
    briefs_dir.mkdir(parents=True)
    (briefs_dir / ".skipped.json").write_text(json.dumps({"skipped": ["2026-10-08#2"]}))
    _build_token()
    assert tap(tokens.mint("skip", {"ticker": "SAMPLE", "briefId": "2026-10-09-3#1"}))["toast"] == "Skipped"
    assert studio.cli.calls == [] and studio.spawned == []
    with session_scope() as s:
        assert s.get(StudioBrief, "SAMPLE").status == "skipped"
    assert json.loads((briefs_dir / ".skipped.json").read_text()) == {"skipped": ["2026-10-08#2", "2026-10-09-3#1"]}


def test_retry_restarts_the_run_once(studio):
    data = tokens.mint("retry", {"slug": "sample-desk"}, slug="sample-desk")
    assert tap(data)["status"] == "studio_retry"
    assert tap(data)["toast"] == "Already restarted"
    assert studio.spawned == ["sample-desk"]


def test_a_stranger_tapping_a_studio_button_is_ignored(studio):
    studio.cli.reply("new", 0, "PROJECT sample-desk\n")
    assert tap(_build_token(), user=999)["status"] == "ignored"
    assert studio.cli.calls == [] and studio.spawned == []


def test_an_unknown_token_is_only_a_toast(studio):
    assert tap("st:deadbeef")["toast"] == "That button has expired"


def test_a_new_the_studio_refuses_says_why(studio):
    studio.cli.reply("new", 1, "", "$ node --import tsx scripts/studio.ts new --brief x\n"
                     "studio new: project sample-desk exists\n[ELIFECYCLE] Command failed with exit code 1.\n")
    assert tap(_build_token())["status"] == "studio_build_failed"
    assert "project sample-desk exists" in studio.sent[-1]["text"]
