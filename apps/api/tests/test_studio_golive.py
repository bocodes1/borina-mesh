"""Bo's CA from Telegram (contracts §14): `/studio ca <slug> <CA>` runs
`studio go-live`, and the go-live stop arrives as a card like any other."""
import json

import pytest

import routes.telegram as tg
from dispatch import studio, studio_media
from dispatch import studio_runner as sr
from dispatch.studio_client import StudioResult
from tests.fakes.studio import BO, buttons, clean_tables, install

MINT = "So11111111111111111111111111111111111111112"
GOLIVE_STOP = {"version": 1, "id": "go-live-1", "slug": "sample-desk", "kind": "go-live",
               "title": "Go live: Sample Desk ($SAMPLE)", "body": "Turn off pre-launch.", "images": [],
               "video": None, "options": [{"id": "yes", "label": "Go live"}, {"id": "no", "label": "Not yet"}],
               "costUsd": None, "createdAt": "2026-10-09T16:00:00.000Z"}


@pytest.fixture
def env(monkeypatch, tmp_path):
    e = install(monkeypatch, tmp_path)
    monkeypatch.setattr(studio_media, "send_stop_media", lambda chat, st: 0)
    monkeypatch.setattr(studio, "_start", lambda target: target())
    yield e
    clean_tables()


def _cmd(text):
    return tg.process_update({"update_id": 9, "message": {"chat": {"id": BO}, "text": text}})


def test_a_ca_runs_go_live_and_cards_its_stop(env):
    env.cli.reply("go-live", 3, "waiting for Bo's answer on go-live-1\nGOLIVE go-live-1\n")
    env.cli.reply("stops", 0, json.dumps({"stops": [GOLIVE_STOP]}) + "\n")
    assert _cmd(f"/studio ca sample-desk {MINT}")["status"] == "studio_ca"
    assert ["go-live", "sample-desk", "--ca", MINT] in env.cli.calls
    card = [m for m in env.sent if m["reply_markup"]][-1]
    assert [label for label, _ in buttons(card)] == ["Go live", "Not yet"]
    assert env.conversed == []


def test_a_ca_for_a_project_already_live_says_so(env):
    env.cli.reply("go-live", 0, "LIVE sample-desk\n")
    _cmd(f"/studio ca sample-desk {MINT}")
    assert "sample-desk is live" in env.sent[-1]["text"]


def test_a_rejected_ca_is_one_line_never_a_trace(env):
    env.cli.reply("go-live", 1, "Error: boom\n    at main (/Users/clawd/dev/launch-studio/scripts/studio.ts:40:9)\n")
    _cmd(f"/studio ca sample-desk {MINT}")
    assert "Couldn't take the CA for sample-desk" in env.sent[-1]["text"]
    assert "studio.ts" not in env.sent[-1]["text"]


@pytest.mark.parametrize("arg", ["ca", "ca sample-desk", f"ca ../x {MINT}", "ca sample-desk not-a-mint!",
                                 f"ca sample-desk {MINT}0OIl", f"ca sample-desk {MINT} extra"])
def test_a_bad_ca_command_never_reaches_the_studio(env, arg):
    _cmd(f"/studio {arg}")
    assert env.cli.calls == [] and "/studio ca &lt;slug&gt; &lt;CA&gt;" in env.sent[-1]["text"]


def test_a_ca_when_the_studio_is_off(env, monkeypatch):
    monkeypatch.setenv("STUDIO_ENABLED", "")
    _cmd(f"/studio ca sample-desk {MINT}")
    assert env.cli.calls == [] and "STUDIO_ENABLED" in env.sent[-1]["text"]


def test_a_run_that_rests_at_ready_asks_for_the_ca_not_a_retry(env):
    sr.drive("sample-desk", run=lambda args, timeout: StudioResult(1, "FAIL sample-desk no progress at ready"),
             sleep=lambda s: None)
    msg = env.sent[-1]
    assert "/studio ca sample-desk &lt;CA&gt;" in msg["text"] and msg["reply_markup"] is None
