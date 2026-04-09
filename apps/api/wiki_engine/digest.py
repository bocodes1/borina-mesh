"""Daily rejection digest — sends a Telegram summary of what the reviewer
filtered in the last 24h."""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from wiki_engine.paths import vault_root, REJECTED_JSONL


async def send_daily_digest() -> int:
    """Read rejected.jsonl, filter to last 24h, send a Telegram summary.

    Returns the number of rejections included.
    """
    try:
        root = vault_root()
    except RuntimeError:
        print("[digest] vault not configured, skipping")
        return 0

    path = root / REJECTED_JSONL
    if not path.exists():
        return 0

    cutoff = datetime.utcnow() - timedelta(hours=24)
    rejections = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        decided = rec.get("decided_at", "")
        try:
            ts = datetime.fromisoformat(decided.replace("Z", ""))
        except ValueError:
            continue
        if ts >= cutoff:
            rejections.append(rec)

    if not rejections:
        return 0

    lines = [
        f"*Wiki Reviewer Digest* ({datetime.utcnow().strftime('%Y-%m-%d')})",
        f"Rejected {len(rejections)} item(s) in the last 24h:",
        "",
    ]
    for i, rec in enumerate(rejections[:15], 1):
        reason = rec.get("reason", "no reason")[:80]
        lines.append(f"{i}. {reason}")
    if len(rejections) > 15:
        lines.append(f"_(+ {len(rejections) - 15} more)_")
    lines.append("")
    lines.append("Override in curator-memory.md if a rejection was wrong.")

    message = "\n".join(lines)
    await _send_telegram(message)
    return len(rejections)


async def _send_telegram(message: str) -> None:
    """Send via python-telegram-bot if configured, else print to stdout."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print(f"[digest] Telegram not configured, digest would be:\n{message}")
        return
    try:
        from telegram import Bot
        bot = Bot(token=token)
        await bot.send_message(chat_id=chat_id, text=message, parse_mode="Markdown")
    except Exception as e:
        print(f"[digest] Telegram send failed: {e}")
