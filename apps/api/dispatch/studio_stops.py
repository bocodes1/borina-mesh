"""Launch Studio stop watcher (M5): NON-LLM, every 2 minutes. Asks the studio
CLI for pending stops and cards each one once: its photos and video first, then
the card with one button per option. It never answers a stop; only Bo's tap does."""
from __future__ import annotations

import re
from typing import Optional

from dispatch import dispatcher, studio_client, studio_media
from dispatch import studio_tokens as tokens
from dispatch.cards import send_card
from dispatch.studio_cards import bo_chat, stop_card

_ID_RE = re.compile(r"^[a-z0-9-]{1,40}$")   # contracts §2.4 Stop.id
_OPT_RE = re.compile(r"^[a-z0-9-]{1,24}$")  # contracts §2.4 StopOption.id


def valid_stop(st) -> bool:
    if not isinstance(st, dict):
        return False
    if not (isinstance(st.get("slug"), str) and studio_client.SLUG_RE.match(st["slug"])):
        return False
    if not (isinstance(st.get("id"), str) and _ID_RE.match(st["id"])):
        return False
    if not isinstance(st.get("title"), str) or not isinstance(st.get("body", ""), str):
        return False
    opts = st.get("options")
    if not isinstance(opts, list) or not 1 <= len(opts) <= 6:
        return False
    for o in opts:
        if not (isinstance(o, dict) and isinstance(o.get("id"), str) and _OPT_RE.match(o["id"])
                and isinstance(o.get("label"), str) and o["label"]):
            return False
    cost = st.get("costUsd")
    return cost is None or (isinstance(cost, (int, float)) and not isinstance(cost, bool) and cost >= 0)


def _key(slug: str, stop_id: str) -> str:
    return f"{slug}/{stop_id}"


def option_tokens(st: dict, note: Optional[str]) -> list[tuple[str, str]]:
    """One token per option. The cost rides in the token itself, so the money
    confirm never depends on a lookup that could miss."""
    base = {"slug": st["slug"], "stopId": st["id"], "note": note, "cost": st.get("costUsd"), "title": st["title"][:80]}
    return [(o["label"], tokens.mint("answer", {**base, "option": o["id"], "label": o["label"]},
                                     slug=st["slug"], stop_id=st["id"]))
            for o in st["options"]]


def send_stop(chat_id: int, st: dict) -> Optional[int]:
    from db import session_scope
    from models import StudioStop

    missing = studio_media.send_stop_media(chat_id, st)
    mid = send_card(chat_id, stop_card(st, option_tokens(st, None), missing))
    if not mid:
        return None  # not carded: the next tick tries again
    dispatcher._record_thread(chat_id, mid, "studio", None, f"{st['slug']} {st['id']}")
    with session_scope() as s:
        s.add(StudioStop(key=_key(st["slug"], st["id"]), slug=st["slug"], stop_id=st["id"],
                         title=st["title"][:80], cost_usd=st.get("costUsd"), message_id=mid))
        s.commit()
    return mid


def watch_stops() -> dict:
    from db import session_scope
    from dispatch.studio_radar import enabled
    from models import StudioStop

    if not enabled():
        return {"status": "disabled"}
    chat = bo_chat()
    if chat is None:
        return {"status": "no_chat"}
    stops = studio_client.pending_stops()
    if stops is None:
        return {"status": "cli_error"}
    sent = 0
    for st in stops:
        if not valid_stop(st):
            print("[studio-stops] skipped a malformed stop")
            continue
        with session_scope() as s:
            if s.get(StudioStop, _key(st["slug"], st["id"])) is not None:
                continue
        if send_stop(chat, st):
            sent += 1
    return {"status": "ok", "sent": sent}
