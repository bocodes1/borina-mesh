"""A Launch Studio stop's images and video, sent to Telegram (M5).

Contracts §9 lets the mesh read exactly these files and nothing else in the
studio. A stop is written by a model that has read third-party text, so every
path is checked before upload: it must resolve (symlinks followed) inside
<studio>/projects/<slug>/, be a regular file with an allowed extension, and fit
Telegram's limits. Anything else is skipped and counted, never sent."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable, Optional

PHOTO_MAX_BYTES = 10 * 1024 * 1024  # Telegram sendPhoto
VIDEO_MAX_BYTES = 50 * 1024 * 1024  # Telegram bot uploads
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
VIDEO_TYPES = {".mp4": "video/mp4"}

Post = Callable[[str, dict, dict], Optional[dict]]


def _post(method: str, data: dict, files: dict) -> Optional[dict]:
    import httpx

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return None
    r = httpx.post(f"https://api.telegram.org/bot{token}/{method}", data=data, files=files, timeout=120)
    r.raise_for_status()
    return r.json()


post: Post = _post  # tests replace this


def _inside(raw, base: Path, max_bytes: int, types: dict) -> tuple[Optional[Path], str]:
    if not isinstance(raw, str) or not raw:
        return None, "not a path"
    p = Path(raw)
    if not p.is_absolute():
        return None, "relative path"
    try:
        real = p.resolve(strict=True)
    except (OSError, RuntimeError):
        return None, "missing"
    if not real.is_relative_to(base):
        return None, "outside the project"
    if not real.is_file():
        return None, "not a file"
    if real.suffix.lower() not in types:
        return None, "wrong type"
    if real.stat().st_size > max_bytes:
        return None, "too big for Telegram"
    return real, ""


def safe_media(stop: dict, studio_root: Path) -> tuple[list[Path], Optional[Path], list[str]]:
    from dispatch.studio_client import SLUG_RE

    slug = stop.get("slug") if isinstance(stop.get("slug"), str) else ""
    if not SLUG_RE.match(slug):
        return [], None, ["bad slug"]
    base = (studio_root / "projects" / slug).resolve()
    images: list[Path] = []
    skipped: list[str] = []
    for raw in (stop.get("images") or [])[:4]:
        p, why = _inside(raw, base, PHOTO_MAX_BYTES, IMAGE_TYPES)
        if p:
            images.append(p)
        else:
            skipped.append(f"image: {why}")
    video = None
    if stop.get("video"):
        video, why = _inside(stop["video"], base, VIDEO_MAX_BYTES, VIDEO_TYPES)
        if video is None:
            skipped.append(f"video: {why}")
    return images, video, skipped


def send_stop_media(chat_id: int, stop: dict) -> int:
    """Photos first (one photo, or one album), then the video. Returns how many attachments were not sent."""
    from dispatch.studio_client import studio_dir

    images, video, skipped = safe_media(stop, studio_dir())
    for why in skipped:
        print(f"[studio-media] {stop.get('id')}: skipped {why}")
    missing = len(skipped)
    try:
        if len(images) == 1:
            p = images[0]
            post("sendPhoto", {"chat_id": str(chat_id)}, {"photo": (p.name, p.read_bytes(), IMAGE_TYPES[p.suffix.lower()])})
        elif images:
            media = [{"type": "photo", "media": f"attach://p{i}"} for i in range(len(images))]
            files = {f"p{i}": (p.name, p.read_bytes(), IMAGE_TYPES[p.suffix.lower()]) for i, p in enumerate(images)}
            post("sendMediaGroup", {"chat_id": str(chat_id), "media": json.dumps(media)}, files)
    except Exception as exc:  # noqa: BLE001 — a failed upload must not lose the card
        print(f"[studio-media] photos failed: {type(exc).__name__}")
        missing += len(images)
    if video:
        try:
            post("sendVideo", {"chat_id": str(chat_id), "supports_streaming": "true"},
                 {"video": (video.name, video.read_bytes(), "video/mp4")})
        except Exception as exc:  # noqa: BLE001
            print(f"[studio-media] video failed: {type(exc).__name__}")
            missing += 1
    return missing
