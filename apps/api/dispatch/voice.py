"""Telegram voice/audio → text via local Whisper (faster-whisper, CPU int8).

No cloud APIs: the model runs on the Mac itself (fast on Apple Silicon) and is
downloaded to the HF cache on first use (env TELEGRAM_VOICE_MODEL, default
"base"). Security: the caller (routes.telegram.process_update) checks the
chat-id allow-list BEFORE calling — media from non-allowed senders is never
downloaded. Duration and size are capped; every failure returns None (caller
asks the user to type instead).
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Optional

MAX_DURATION_SECONDS = 180
MAX_FILE_BYTES = 20 * 1024 * 1024  # Telegram bot-API download cap

_model = None


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        name = os.getenv("TELEGRAM_VOICE_MODEL", "base")
        _model = WhisperModel(name, device="cpu", compute_type="int8")
    return _model


def _token() -> str:
    return os.getenv("TELEGRAM_BOT_TOKEN", "").strip()


def _download(file_id: str) -> Optional[Path]:
    import httpx

    r = httpx.get(
        f"https://api.telegram.org/bot{_token()}/getFile",
        params={"file_id": file_id},
        timeout=15,
    )
    r.raise_for_status()
    info = r.json()
    file_path = (info.get("result") or {}).get("file_path")
    if not info.get("ok") or not file_path:
        return None
    fd, tmp = tempfile.mkstemp(suffix=Path(file_path).suffix or ".oga")
    os.close(fd)
    out = Path(tmp)
    with httpx.stream(
        "GET", f"https://api.telegram.org/file/bot{_token()}/{file_path}", timeout=60
    ) as resp:
        resp.raise_for_status()
        with out.open("wb") as fh:
            for chunk in resp.iter_bytes():
                fh.write(chunk)
    return out


def transcribe_file(path: Path) -> str:
    segments, _info = _get_model().transcribe(str(path), vad_filter=True)
    return " ".join(s.text.strip() for s in segments).strip()


def transcribe_telegram_media(media: dict) -> Optional[str]:
    """file_id dict (message.voice / .audio) → transcript, or None on any
    failure or cap breach. Caller has already verified the sender."""
    if int(media.get("duration") or 0) > MAX_DURATION_SECONDS:
        return None
    if int(media.get("file_size") or 0) > MAX_FILE_BYTES:
        return None
    file_id = media.get("file_id")
    if not file_id or not _token():
        return None
    path: Optional[Path] = None
    try:
        path = _download(file_id)
        if not path:
            return None
        return transcribe_file(path) or None
    except Exception as exc:  # noqa: BLE001
        print(f"[voice] transcription failed: {exc}")
        return None
    finally:
        if path:
            path.unlink(missing_ok=True)
