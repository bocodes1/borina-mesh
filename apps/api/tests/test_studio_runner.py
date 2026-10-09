"""Detached `studio run` (M5): outcome mapping, busy retries, and what Bo hears."""
import subprocess

import pytest
from sqlalchemy import delete

from db import session_scope
from dispatch import dispatcher, studio_tokens
from dispatch import studio_runner as sr
from dispatch.studio_client import StudioResult
from models import StudioToken

BO = 6452258223


@pytest.fixture
def sent(monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", str(BO))
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", str(BO))
    out = []
    monkeypatch.setattr(dispatcher, "send_telegram_message",
                        lambda c, t, reply_markup=None: out.append({"chat_id": c, "text": t, "reply_markup": reply_markup}) or len(out))
    yield out
    with session_scope() as s:
        s.exec(delete(StudioToken))
        s.commit()


def _always(res):
    return lambda args, timeout: res


@pytest.mark.parametrize("res,kind,detail", [
    (StudioResult(3, "STOP sample-desk spec-1"), "stop", "spec-1"),
    (StudioResult(0, "STAGE sample-desk live"), "stage", "live"),
    (StudioResult(1, "FAIL sample-desk locked (held by pid 5151)"), "locked", "locked (held by pid 5151)"),
    (StudioResult(1, "FAIL sample-desk busy (1 of 1 runs going)"), "busy", "busy (1 of 1 runs going)"),
    (StudioResult(1, "FAIL sample-desk no progress at build"), "fail", "no progress at build"),
    (StudioResult(None, "", [], "timed out after 86400 s"), "fail", "timed out after 86400 s"),
])
def test_outcome(res, kind, detail):
    assert sr.outcome(res, "sample-desk") == (kind, detail)


def test_drive_waits_out_busy_then_stays_quiet_at_a_stop(sent):
    replies = iter([StudioResult(1, "FAIL sample-desk busy (1 of 1 runs going)")] * 2 + [StudioResult(3, "STOP sample-desk spec-1")])
    calls, sleeps = [], []
    kind = sr.drive("sample-desk", run=lambda args, timeout: calls.append(args) or next(replies), sleep=sleeps.append)
    assert kind == "stop" and calls == [["run", "sample-desk"]] * 3 and len(sleeps) == 2
    assert sent == []


def test_a_failed_run_sends_a_failure_card_with_retry(sent):
    assert sr.drive("sample-desk", run=_always(StudioResult(1, "FAIL sample-desk timed out after 360 min at build")),
                    sleep=lambda s: None) == "fail"
    card = sent[0]
    assert "sample-desk stopped" in card["text"] and "timed out after 360 min at build" in card["text"]
    tok = studio_tokens.peek(card["reply_markup"]["inline_keyboard"][0][0]["callback_data"])
    assert tok["kind"] == "retry" and tok["payload"] == {"slug": "sample-desk"}


def test_live_is_one_line_and_a_mid_pipeline_stage_offers_continue(sent):
    sr.drive("sample-desk", run=_always(StudioResult(0, "STAGE sample-desk live")), sleep=lambda s: None)
    assert sent[-1]["text"] == "sample-desk is live." and sent[-1]["reply_markup"] is None
    sr.drive("sample-desk", run=_always(StudioResult(0, "STAGE sample-desk kit")), sleep=lambda s: None)
    assert "paused at kit" in sent[-1]["text"]
    assert sent[-1]["reply_markup"]["inline_keyboard"][0][0]["text"] == "Continue"


def test_a_project_another_run_holds_is_silent(sent):
    sr.drive("sample-desk", run=_always(StudioResult(1, "FAIL sample-desk locked (held by pid 5151)")), sleep=lambda s: None)
    assert sent == []


def test_nothing_is_sent_when_the_chat_is_not_allow_listed(sent, monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "")
    sr.drive("sample-desk", run=_always(StudioResult(1, "FAIL sample-desk no progress at build")), sleep=lambda s: None)
    assert sent == []


def test_spawn_run_detaches(monkeypatch, tmp_path):
    monkeypatch.setattr(sr, "REPO", tmp_path)
    seen = {}

    class FakeProc:
        pid = 4242

    def fake_popen(args, **kw):
        seen["args"] = args
        seen.update(kw)
        return FakeProc()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    assert sr.spawn_run("sample-desk") == 4242
    assert seen["args"][-2:] == ["--slug", "sample-desk"] and seen["args"][1].endswith("scripts/studio_run.py")
    assert seen["start_new_session"] is True and (tmp_path / "logs").is_dir()


def test_spawn_run_refuses_a_bad_slug(monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("must not start anything"))
    assert sr.spawn_run("../x") is None
