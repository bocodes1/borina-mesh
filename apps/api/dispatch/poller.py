"""Telegram getUpdates poller (Phase 4 §3) — inbound dispatch without a webhook.

Enabled only when TELEGRAM_DISPATCH_MODE=polling AND a bot token is set. Long-
polls api.telegram.org (outbound HTTPS — nothing public is exposed) and feeds
every update through the SAME fail-closed pipeline as the webhook
(`routes.telegram.process_update`: allow-list → intent → idempotent enqueue).
The webhook's secret-token check doesn't apply here: the transport is
authenticated by the bot token in the URL we dial out to.

Telegram allows ONE getUpdates consumer per bot — on start we call
deleteWebhook so polling owns the stream. No other poller may share the token
(two pollers split the messages between them).

Offset is in-memory only: on restart we re-fetch unacked updates and rely on
the enqueue's update_id idempotency, so nothing double-runs.
"""
from __future__ import annotations

import asyncio
import os
from typing import Callable, Optional

POLL_TIMEOUT_SECONDS = 25


def _token() -> str:
    return os.getenv("TELEGRAM_BOT_TOKEN", "").strip()


def enabled() -> bool:
    return (
        os.getenv("TELEGRAM_DISPATCH_MODE", "").strip().lower() == "polling"
        and bool(_token())
    )


def _api(method: str) -> str:
    return f"https://api.telegram.org/bot{_token()}/{method}"


def fetch_updates(offset: Optional[int]) -> list[dict]:
    import httpx

    params: dict = {
        "timeout": POLL_TIMEOUT_SECONDS,
        "allowed_updates": '["message","callback_query"]',
    }
    if offset is not None:
        params["offset"] = offset
    r = httpx.get(_api("getUpdates"), params=params, timeout=POLL_TIMEOUT_SECONDS + 10)
    r.raise_for_status()
    data = r.json()
    return data.get("result", []) if data.get("ok") else []


def delete_webhook() -> None:
    """Polling owns the stream: a registered webhook makes getUpdates 409."""
    import httpx

    try:
        httpx.post(_api("deleteWebhook"), timeout=10)
    except Exception as exc:  # noqa: BLE001
        print(f"[telegram-poller] deleteWebhook failed: {exc}")


class TelegramPoller:
    def __init__(self, fetch: Optional[Callable[[Optional[int]], list[dict]]] = None) -> None:
        self._task: Optional[asyncio.Task] = None
        self._stop = False
        self.offset: Optional[int] = None
        self._fetch = fetch or fetch_updates

    def start(self) -> None:
        if self._task is not None or not enabled():
            return
        self._stop = False
        delete_webhook()
        self._task = asyncio.create_task(self._loop())
        print("[telegram-poller] started (getUpdates long-poll)")

    def stop(self) -> None:
        self._stop = True
        if self._task:
            self._task.cancel()
            self._task = None

    async def poll_once(self) -> int:
        """One fetch + process cycle. Always advances the offset (acks), even
        for dropped/erroring updates — never re-deliver."""
        import routes.telegram as tg

        updates = await asyncio.to_thread(self._fetch, self.offset)
        for u in updates:
            uid = u.get("update_id")
            if uid is not None:
                self.offset = max(self.offset or 0, uid + 1)
            try:
                tg.process_update(u)
            except Exception as exc:  # noqa: BLE001
                print(f"[telegram-poller] update error: {exc}")
        return len(updates)

    async def _loop(self) -> None:
        while not self._stop:
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                print(f"[telegram-poller] poll error: {exc}")
                await asyncio.sleep(5.0)


poller = TelegramPoller()
