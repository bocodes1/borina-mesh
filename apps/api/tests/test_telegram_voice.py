"""Telegram voice routing (Phase 5): voice note → local Whisper transcript →
the SAME intent/dispatch pipeline as text. Security: transcription/download
happen only AFTER the allow-list check; caps enforced; failures fail closed.
"""
from types import SimpleNamespace

import pytest

import routes.telegram as tg
from dispatch import dispatcher, voice

BO = 6452258223


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", str(BO))
    monkeypatch.setattr(dispatcher, "send_telegram_message", lambda *a, **k: None)


def _spy_enqueue(monkeypatch):
    calls = []

    def fake(text, agent, update_id, chat_id):
        calls.append({"text": text, "agent": agent, "chat_id": chat_id})
        return SimpleNamespace(id=len(calls))

    monkeypatch.setattr(tg, "enqueue_job", fake)
    return calls


def _voice_update(update_id, chat_id, duration=10):
    return {
        "update_id": update_id,
        "message": {
            "chat": {"id": chat_id},
            "voice": {"file_id": "f1", "duration": duration, "file_size": 9000},
        },
    }


def test_voice_transcript_routes_like_text(monkeypatch):
    calls = _spy_enqueue(monkeypatch)
    sent = []
    monkeypatch.setattr(dispatcher, "send_telegram_message", lambda cid, txt: sent.append(txt))
    monkeypatch.setattr(voice, "transcribe_telegram_media", lambda m: "research NVDA earnings")
    res = tg.process_update(_voice_update(500, BO))
    assert res["status"] == "dispatched"
    assert calls[0]["text"] == "research NVDA earnings"
    assert any("Heard" in s for s in sent)


def test_voice_from_non_allowed_never_downloads(monkeypatch):
    calls = _spy_enqueue(monkeypatch)
    monkeypatch.setattr(
        voice, "transcribe_telegram_media",
        lambda m: pytest.fail("media from a non-allowed sender must never be touched"),
    )
    res = tg.process_update(_voice_update(501, 999))
    assert res["status"] == "ignored"
    assert calls == []


def test_voice_transcribe_failure_fails_closed(monkeypatch):
    calls = _spy_enqueue(monkeypatch)
    monkeypatch.setattr(voice, "transcribe_telegram_media", lambda m: None)
    res = tg.process_update(_voice_update(502, BO))
    assert res["status"] == "transcribe_failed"
    assert calls == []


def test_caps_block_without_download(monkeypatch):
    monkeypatch.setattr(voice, "_download", lambda fid: pytest.fail("must not download"))
    assert voice.transcribe_telegram_media({"file_id": "x", "duration": 9999}) is None
    assert voice.transcribe_telegram_media({"file_id": "x", "duration": 5, "file_size": 10**9}) is None


def test_no_token_no_download(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(voice, "_download", lambda fid: pytest.fail("must not download"))
    assert voice.transcribe_telegram_media({"file_id": "x", "duration": 5}) is None
