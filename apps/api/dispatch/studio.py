"""Launch Studio on Telegram (M5): button taps, notes and /studio.

Everything here is reached through routes.telegram.process_update, after its
fail-closed allow-list. Buttons carry `st:` tokens (dispatch.studio_tokens); a
tap claims its token before acting, so a double tap or a re-delivered update
acts once. Nothing here answers a stop on its own: only Bo's tap reaches
`studio answer`."""
from __future__ import annotations

import threading
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
    if kind == "answer":
        return _answer(data, tok, chat_id)
    if kind == "confirm":
        return _confirm(data, tok, chat_id)
    if kind == "cancel":
        return _cancel(data, tok, chat_id)
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


def _mark_stop(slug: str, stop_id: str) -> None:
    from db import session_scope
    from models import StudioStop

    with session_scope() as s:
        row = s.get(StudioStop, f"{slug}/{stop_id}")
        if row is not None:
            row.status = "answered"
            s.add(row)
            s.commit()


def _answer(data: str, tok: dict, chat_id: int) -> dict:
    from dispatch.cards import send_card
    from dispatch.studio_cards import confirm_card

    p = tok["payload"]
    if tok["used"]:
        return _toast("studio_answer", "Already done")
    if p.get("cost") is not None and p.get("option") == "yes":
        # Money: this tap only asks. Spending needs the separate Confirm tap.
        stop = {"slug": p["slug"], "title": p.get("title") or p["stopId"], "costUsd": p["cost"]}
        confirm = tokens.mint("confirm", p, slug=p["slug"], stop_id=p["stopId"])
        cancel = tokens.mint("cancel", {"slug": p["slug"], "stopId": p["stopId"], "confirm": confirm},
                             slug=p["slug"], stop_id=p["stopId"])
        send_card(chat_id, confirm_card(stop, p.get("label") or "Yes", confirm, cancel))
        return _toast("studio_confirm_asked", "Confirm the spend")
    if tokens.claim(data) is None:
        return _toast("studio_answer", "Already done")
    return _submit(data, p, chat_id)


def _confirm(data: str, tok: dict, chat_id: int) -> dict:
    if tokens.claim(data) is None:
        return _toast("studio_answer", "Already done")
    return _submit(data, tok["payload"], chat_id)


def _cancel(data: str, tok: dict, chat_id: int) -> dict:
    if tokens.claim(data) is None:
        return _toast("studio_cancel", "Already done")
    p = tok["payload"]
    tokens.claim(p.get("confirm", ""))  # its Confirm button can't spend later
    _say(chat_id, f"Nothing spent. {p['slug']} is still waiting on {p['stopId']}.")
    return _toast("studio_cancel", "Cancelled")


def _submit(data: str, p: dict, chat_id: int) -> dict:
    slug, stop_id, option, note = p["slug"], p["stopId"], p["option"], p.get("note")
    args = ["answer", slug, stop_id, option, "--by", "telegram"]
    if note:
        args.append(f"--note={note}")  # one argv element, so a note starting with "-" is never a flag
    res = studio_client.run(args, timeout=90)
    if res.ok and res.last.startswith(f"ANSWERED {slug} {stop_id} "):
        tokens.retire_stop(slug, stop_id)
        _mark_stop(slug, stop_id)
        studio_runner.spawn_run(slug)
        _say(chat_id, f"{slug}: {option} on {stop_id}. Continuing.")
        return _toast("studio_answered", "Answered", slug=slug)
    if "already answered" in f"{res.last} {res.error}".lower():
        tokens.retire_stop(slug, stop_id)
        _mark_stop(slug, stop_id)
        return _toast("studio_answer", "Already answered")
    tokens.release(data)
    _say(chat_id, f"Couldn't answer {stop_id}: {res.error or 'the studio gave no ANSWERED line'}")
    return _toast("studio_answer_failed", "Failed")


def handle_reply(thread, text: str, chat_id: int) -> dict:
    """Bo replied to a stop card: the text is a note, and he picks the answer it goes with."""
    from dispatch.cards import send_card
    from dispatch.studio_cards import note_card
    from dispatch.studio_stops import option_tokens, valid_stop

    slug, _, stop_id = (thread.prompt or "").partition(" ")
    note = (text or "").strip()[:1000]
    if not note:
        return _toast("studio_note_empty", "")
    stops = studio_client.pending_stops()
    if stops is None:
        _say(chat_id, "Couldn't reach the studio. Send the note again in a minute.")
        return _toast("studio_note_failed", "")
    st = next((s for s in stops if valid_stop(s) and s["slug"] == slug and s["id"] == stop_id), None)
    if st is None:
        _say(chat_id, f"{stop_id} isn't waiting any more.")
        return _toast("studio_note_stale", "")
    send_card(chat_id, note_card(st, note, option_tokens(st, note)))
    return _toast("studio_note", "", slug=slug)


def _start(target) -> None:
    threading.Thread(target=target, daemon=True).start()


def radar_line() -> str:
    from db import session_scope
    from models import PipelineRun

    with session_scope() as s:
        row = s.get(PipelineRun, "studio-radar")
        if row is None or row.last_run_at is None:
            return "Radar: no run yet."
        state = "ok" if row.last_run_ok else "failed"
        return f"Radar: last run {row.last_run_at:%Y-%m-%d %H:%M} UTC, {state} ({row.last_run_detail or '-'})"


def send_status(chat_id: int) -> None:
    from dispatch.cards import send_card
    from dispatch.studio_cards import status_card

    projects = studio_client.projects()
    if projects is None:
        _say(chat_id, "Launch Studio isn't answering right now (studio status failed).")
        return
    send_card(chat_id, status_card(projects, studio_client.pending_stops() or [], radar_line()))


def start_radar_now(chat_id: int) -> None:
    from dispatch import studio_radar

    if not studio_radar.enabled():
        _say(chat_id, "Launch Studio is off: set STUDIO_ENABLED=1 in the mesh's .env.")
        return
    _say(chat_id, "Radar started. New briefs arrive here in about 30 to 40 minutes.")
    _start(lambda: studio_radar.run_radar_job(force=True))
