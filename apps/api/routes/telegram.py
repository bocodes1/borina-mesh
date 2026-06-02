"""Telegram webhook (spec §8b.2) — the security boundary for auto-dispatch.

Order of checks (all must pass):
1. **secret-token header** (`X-Telegram-Bot-Api-Secret-Token` == TELEGRAM_WEBHOOK_SECRET)
   — fail closed: if the secret isn't configured or doesn't match → 403.
2. **allow-list** (chat_id ∈ TELEGRAM_ALLOWED_CHAT_IDS) — fail closed: empty list
   ⇒ everything ignored. Non-allowed senders are silently dropped (200, no dispatch).
3. **intent** — forbidden actions are refused (no dispatch); low-confidence asks to
   rephrase. Only a dispatchable research/intel intent is acked + enqueued.

Returns 200 fast so Telegram doesn't retry; the agent runs in the background.
"""
import os
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from dispatch import dispatcher
from dispatch.intent import resolve_intent, Intent

router = APIRouter(prefix="/api/telegram", tags=["telegram"])

SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"


def _check_secret(header_value: str) -> bool:
    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    # Fail closed: no configured secret ⇒ reject everything.
    return bool(secret) and header_value == secret


def _allowed_ids() -> set[int]:
    raw = os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "").strip()
    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if part:
            try:
                ids.add(int(part))
            except ValueError:
                pass
    return ids


def _run_dispatch(intent: Intent, chat_id: int, requested_at: str) -> None:
    import asyncio

    try:
        asyncio.run(dispatcher.dispatch_intent(intent, chat_id, requested_at))
    except Exception as exc:  # noqa: BLE001
        print(f"[telegram] dispatch failed: {exc}")
        dispatcher.send_telegram_message(chat_id, f"⚠️ Dispatch failed: {exc}")


def enqueue_dispatch(background: BackgroundTasks, intent: Intent, chat_id: int, requested_at: str) -> None:
    """Indirection so tests can spy on enqueue without running the agent."""
    background.add_task(_run_dispatch, intent, chat_id, requested_at)


@router.post("/webhook")
async def webhook(request: Request, background: BackgroundTasks):
    # 1. Secret-token header — hard reject (this is the security boundary).
    if not _check_secret(request.headers.get(SECRET_HEADER, "")):
        raise HTTPException(403, "invalid or missing secret token")

    update = await request.json()
    msg = update.get("message") or update.get("edited_message") or {}
    chat = msg.get("chat", {}) or {}
    chat_id = chat.get("id")
    text = msg.get("text", "") or ""

    # 2. Allow-list — fail closed; silently drop anything not from Bo.
    if chat_id is None or chat_id not in _allowed_ids():
        print(f"[telegram] ignored update from chat_id={chat_id}")
        return {"ok": True, "status": "ignored"}

    # 3. Intent.
    intent = resolve_intent(text)
    if intent.forbidden:
        dispatcher.send_telegram_message(
            chat_id,
            f"That maps to a {intent.forbidden_reason} action — not auto-dispatchable. "
            f"I only run read-only research/intel from Telegram.",
        )
        return {"ok": True, "status": "refused", "reason": intent.forbidden_reason}

    if not intent.dispatchable:
        dispatcher.send_telegram_message(
            chat_id, "I couldn't confidently route that — could you rephrase?"
        )
        return {"ok": True, "status": "clarify"}

    # Ack fast, dispatch in the background.
    dispatcher.send_telegram_message(chat_id, f"On it — dispatching {intent.agent}…")
    enqueue_dispatch(background, intent, chat_id, datetime.utcnow().isoformat())
    return {"ok": True, "status": "dispatched", "agent": intent.agent}
