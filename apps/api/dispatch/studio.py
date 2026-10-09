"""Launch Studio on Telegram (M5): button taps, notes and /studio.

Everything here is reached through routes.telegram.process_update, after its
fail-closed allow-list. Buttons carry `st:` tokens (dispatch.studio_tokens); a
tap claims its token before acting, so a double tap or a re-delivered update
acts once. Nothing here answers a stop on its own: only Bo's tap reaches
`studio answer`."""
from __future__ import annotations

from typing import Optional

from dispatch import dispatcher, studio_client, studio_runner
from dispatch import studio_tokens as tokens
from dispatch.telegram_format import format_telegram


def _say(chat_id: int, text: str) -> None:
    dispatcher.send_telegram_message(chat_id, format_telegram(text))


def _toast(status: str, toast: str, **extra) -> dict:
    return {"ok": True, "status": status, "toast": toast, **extra}


def _mark_brief(ticker: Optional[str], status: str, slug: Optional[str]) -> None:
    if not ticker:
        return
    from db import session_scope
    from models import StudioBrief

    with session_scope() as s:
        row = s.get(StudioBrief, ticker)
        if row is None:
            return
        row.status = status
        row.slug = slug or row.slug
        s.add(row)
        s.commit()


def handle_callback(data: str, chat_id: int) -> dict:
    tok = tokens.peek(data)
    if tok is None:
        return _toast("studio_unknown", "That button has expired")
    kind = tok["kind"]
    if kind == "build":
        return _build(data, tok, chat_id)
    if kind == "skip":
        return _skip(data, tok)
    if kind == "retry":
        return _retry(data, tok, chat_id)
    return _toast("studio_unknown", "")


def _build(data: str, tok: dict, chat_id: int) -> dict:
    if tokens.claim(data) is None:
        return _toast("studio_build", "Already started")
    p = tok["payload"]
    res = studio_client.run(["new", "--brief", f"{p['briefsFile']}#{p['briefId']}"], timeout=180)
    slug = res.last[len("PROJECT "):].strip() if res.ok and res.last.startswith("PROJECT ") else ""
    if not studio_client.SLUG_RE.match(slug):
        tokens.release(data)  # nothing was created: let Bo tap again
        _say(chat_id, f"Couldn't start ${p.get('ticker', '?')}: {res.error or 'the studio gave no PROJECT line'}")
        return _toast("studio_build_failed", "Failed")
    _mark_brief(p.get("ticker"), "building", slug)
    studio_runner.spawn_run(slug)
    _say(chat_id, f"Building {slug}. Its spec card comes here when it's ready.")
    return _toast("studio_build", "Started", slug=slug)


def _skip(data: str, tok: dict) -> dict:
    if tokens.claim(data) is None:
        return _toast("studio_skip", "Already skipped")
    p = tok["payload"]
    _mark_brief(p.get("ticker"), "skipped", None)
    if p.get("briefId"):
        from dispatch.studio_radar import add_skipped

        add_skipped(p["briefId"])  # contracts §11: the dashboard sees Telegram skips too
    return _toast("studio_skip", "Skipped")


def _retry(data: str, tok: dict, chat_id: int) -> dict:
    if tokens.claim(data) is None:
        return _toast("studio_retry", "Already restarted")
    slug = tok["payload"].get("slug", "")
    if studio_runner.spawn_run(slug) is None:
        return _toast("studio_retry_bad", "Unknown project")
    _say(chat_id, f"Restarted {slug}.")
    return _toast("studio_retry", "Restarted", slug=slug)
