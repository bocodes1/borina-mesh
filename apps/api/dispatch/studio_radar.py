"""Scheduled Launch Studio radar (M5, ruling R4).

Every STUDIO_RADAR_EVERY_H hours (default 6, America/New_York), outside
STUDIO_QUIET_HOURS: run `studio radar --headless`, read the briefs JSON it names,
and card each brief whose ticker the mesh has never carded (Build / Skip). Big
swings share one card. Off unless STUDIO_ENABLED=1, because every run spends
Claude usage."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/New_York")
RADAR_TIMEOUT_S = 50 * 60  # the studio itself stops at about 41 min (10 min scan + 30 min session)
EVERY_H_CHOICES = (1, 2, 3, 4, 6, 8, 12, 24)
_TICKER_RE = re.compile(r"^[A-Z0-9]{2,12}$")
_ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(-\d+)?#(\d+|swing-\d+)$")
_QUIET_RE = re.compile(r"^\s*(\d{1,2})\s*-\s*(\d{1,2})\s*$")
_LIMITS = {"name": 60, "pitch": 280, "moneyLoop": 600, "attention": 600, "larpSource": 300}  # contracts §2.1


def enabled() -> bool:
    return os.getenv("STUDIO_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


def every_hours() -> int:
    raw = os.getenv("STUDIO_RADAR_EVERY_H", "").strip()
    try:
        n = int(raw) if raw else 6
    except ValueError:
        return 6
    if n == 0:
        return 0
    return n if n in EVERY_H_CHOICES else 6


def quiet_hours() -> Optional[tuple[int, int]]:
    m = _QUIET_RE.match(os.getenv("STUDIO_QUIET_HOURS", ""))
    if not m:
        return None
    a, b = int(m.group(1)), int(m.group(2))
    return (a, b) if 0 <= a <= 23 and 0 <= b <= 24 and a != b else None


def is_quiet(now: datetime, q: Optional[tuple[int, int]]) -> bool:
    if q is None:
        return False
    h = now.astimezone(TZ).hour
    a, b = q
    return a <= h < b if a < b else (h >= a or h < b)


def _briefs_path(rel: str) -> Optional[Path]:
    from dispatch.studio_client import studio_dir

    base = (studio_dir() / "radar" / "briefs").resolve()
    p = (studio_dir() / rel).resolve()
    return p if p.suffix == ".json" and p.is_relative_to(base) and p.is_file() else None


def valid_brief(b) -> bool:
    if not isinstance(b, dict):
        return False
    if not (isinstance(b.get("id"), str) and _ID_RE.match(b["id"])):
        return False
    if not (isinstance(b.get("ticker"), str) and _TICKER_RE.match(b["ticker"])):
        return False
    if b.get("lane") not in ("A", "B", "C") or not isinstance(b.get("bigSwing"), bool):
        return False
    rank = b.get("rank")
    if rank is not None and (isinstance(rank, bool) or not isinstance(rank, int) or rank < 1):
        return False
    return all(isinstance(b.get(k), str) and 0 < len(b[k]) <= n for k, n in _LIMITS.items())


def read_briefs(rel: str) -> Optional[list[dict]]:
    """The valid briefs of a file under radar/briefs/, or None if the path or the file is wrong."""
    p = _briefs_path(rel)
    if p is None:
        return None
    try:
        doc = json.loads(p.read_text())
    except (OSError, ValueError):
        return None
    items = doc.get("briefs") if isinstance(doc, dict) else None
    return [b for b in items if valid_brief(b)] if isinstance(items, list) else None


def _carded(ticker: str) -> bool:
    from db import session_scope
    from models import StudioBrief

    with session_scope() as s:
        return s.get(StudioBrief, ticker) is not None


def _remember(b: dict, rel: str) -> None:
    from db import session_scope
    from models import StudioBrief

    with session_scope() as s:
        s.add(StudioBrief(ticker=b["ticker"], briefs_file=rel, brief_id=b["id"], name=b["name"],
                          big_swing=b["bigSwing"]))
        s.commit()


def _last_ok() -> Optional[bool]:
    from db import session_scope
    from models import PipelineRun

    with session_scope() as s:
        row = s.get(PipelineRun, "studio-radar")
        return None if row is None else row.last_run_ok


def _skipped_file() -> Path:
    from dispatch.studio_client import studio_dir

    return studio_dir() / "radar" / "briefs" / ".skipped.json"


def skipped_ids() -> set[str]:
    """Brief ids Bo skipped, on the dashboard or here (contracts §11 radar/briefs/.skipped.json)."""
    try:
        doc = json.loads(_skipped_file().read_text())
    except (OSError, ValueError):
        return set()
    items = doc.get("skipped") if isinstance(doc, dict) else None
    return {s for s in items if isinstance(s, str)} if isinstance(items, list) else set()


def add_skipped(brief_id: str) -> None:
    """Record a Telegram skip where the dashboard reads it: atomic replace, keeping what the dashboard wrote."""
    f = _skipped_file()
    if not f.parent.is_dir():
        return
    ids = skipped_ids() | {brief_id}
    tmp = f.with_name(f".skipped.{os.getpid()}.tmp")
    tmp.write_text(json.dumps({"skipped": sorted(ids)}))
    os.replace(tmp, f)


def run_radar_job(now: Optional[datetime] = None, force: bool = False) -> dict:
    """One radar run → brief cards. `force` (Bo's /studio radar) ignores quiet hours, never the off switch."""
    from dispatch import dispatcher, studio_client
    from dispatch import studio_tokens as tokens
    from dispatch.cards import send_card
    from dispatch.studio_cards import bo_chat, brief_card, swings_card
    from dispatch.telegram_format import format_telegram
    from pipeline_status import record_pipeline_run

    now = now or datetime.now(TZ)
    if not enabled():
        return {"status": "disabled"}
    if not force and is_quiet(now, quiet_hours()):
        return {"status": "quiet"}
    chat = bo_chat()
    if chat is None:
        return {"status": "no_chat"}

    res = studio_client.run(["radar", "--headless"], timeout=RADAR_TIMEOUT_S)
    rel = res.last[len("BRIEFS "):].strip() if res.ok and res.last.startswith("BRIEFS ") else None
    briefs = read_briefs(rel) if rel else None
    if briefs is None:
        reason = res.error or ("unreadable briefs file" if rel else "the studio gave no BRIEFS line")
        was_ok = _last_ok()
        record_pipeline_run("studio-radar", False, reason)
        if force or was_ok is not False:  # say it once, not every 6 h; always when Bo asked
            dispatcher.send_telegram_message(chat, format_telegram(f"Studio radar failed: {reason}"))
        return {"status": "failed", "reason": reason}

    skipped = skipped_ids()
    fresh, seen = [], set()
    for b in briefs:
        if b["id"] in skipped or b["ticker"] in seen or _carded(b["ticker"]):
            continue
        seen.add(b["ticker"])
        fresh.append(b)
    regular = sorted((b for b in fresh if not b["bigSwing"]), key=lambda b: b["rank"] or 99)
    swings = [b for b in fresh if b["bigSwing"]]

    sent = 0
    for b in regular:
        build = tokens.mint("build", {"briefsFile": rel, "briefId": b["id"], "ticker": b["ticker"]})
        skip = tokens.mint("skip", {"ticker": b["ticker"], "briefId": b["id"]})
        if send_card(chat, brief_card(b, build, skip)):
            _remember(b, rel)
            sent += 1
    if swings:
        pairs = [(b, tokens.mint("build", {"briefsFile": rel, "briefId": b["id"], "ticker": b["ticker"]})) for b in swings]
        if send_card(chat, swings_card(pairs)):
            for b in swings:
                _remember(b, rel)
    record_pipeline_run("studio-radar", True, f"{sent} new, {len(swings)} swings")
    if force and not sent and not swings:
        dispatcher.send_telegram_message(chat, format_telegram("Radar done: no new briefs this time."))
    return {"status": "ok", "sent": sent, "swings": len(swings)}
