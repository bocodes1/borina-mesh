"""Conversational lane — quick LLM reply + calendar-event extraction.

Casual messages ("photo shoot Monday 12pm", "what's the vibe for Monday?") should
get a fast, natural reply — NOT the heavy "dispatching researcher → full report"
ceremony. This makes one `claude -p` one-shot call that returns BOTH a short
conversational reply AND, if the message mentions/asks to schedule something, the
extracted event. The event becomes an approval Card (the user taps Approve — the
only thing that writes the calendar). No autonomous calendar write happens here.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timedelta
from typing import Optional

CLAUDE_BIN = os.getenv("CLAUDE_BIN", "claude")
CONVERSE_TIMEOUT = int(os.getenv("CONVERSE_TIMEOUT_SECONDS", "45"))

_PROMPT = """You are Borina, the user's terse, friendly personal assistant, texting them back.
Today is {today} ({weekday}); timezone America/Toronto. Keep it natural and brief.

User said: "{text}"
{context}
Respond with JSON ONLY, no prose around it, exactly this shape:
{{"reply": "<1-3 sentence natural reply, plain text, no markdown headings, no 'dispatching', just talk>",
  "event": null OR {{"summary": "<short title>", "start": "<ISO local e.g. {sample}>", "end": "<ISO, default start+1h>"}}}}

Set "event" ONLY if the message mentions or asks to schedule a specific dated/timed thing
(a shoot, meeting, call, appointment, reminder). Pick the most likely date/time. If they say
"add it"/"put it on my calendar" referring to something above, use that. Otherwise event=null.
If you created an event, keep the reply casual — they'll get an Approve button."""


def _claude(prompt: str, timeout: int = CONVERSE_TIMEOUT) -> str:
    try:
        r = subprocess.run(
            [CLAUDE_BIN, "-p", prompt],
            capture_output=True, text=True, timeout=timeout,
        )
        return ((r.stdout or "").strip() or (r.stderr or "").strip())
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


_PLAIN_PROMPT = ("You are Borina, the user's friendly personal assistant. Reply to this in 1-2 "
                 "short, natural sentences, plain text only:\n\n{text}")


def _parse_json(text: str) -> Optional[dict]:
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return None
    for candidate in (m.group(0), re.sub(r"\n\s*", " ", m.group(0))):
        try:
            d = json.loads(candidate)
            if isinstance(d, dict):
                return d
        except json.JSONDecodeError:
            continue
    return None


def converse(text: str, *, context: str = "", now: Optional[datetime] = None) -> dict:
    """Return {'reply': str, 'event': dict|None}. Robust to LLM/parse failure."""
    now = now or datetime.now()
    sample = (now.replace(hour=12, minute=0, second=0, microsecond=0)).strftime("%Y-%m-%dT%H:%M:%S")
    ctx = f'Context (the message it may refer to): "{context}"\n' if context else ""
    out = _claude(_PROMPT.format(
        today=now.date().isoformat(), weekday=now.strftime("%A"),
        text=text.replace('"', "'"), context=ctx, sample=sample,
    ))
    data = _parse_json(out)
    event = data.get("event") if data else None
    if not (isinstance(event, dict) and event.get("summary") and event.get("start")):
        event = None

    reply = str(data.get("reply")).strip() if (data and data.get("reply")) else ""
    if not reply:
        # Structured call gave no usable reply — use raw prose if it wasn't JSON,
        # else make one plain conversational call so the user still gets an answer.
        if out and "{" not in out:
            reply = out[:600]
        else:
            reply = _claude(_PLAIN_PROMPT.format(text=text)).strip()[:600]
    return {"reply": reply or "On it.", "event": event}


# ── calendar event → approval card (the user-initiated write happens on tap) ────
def _plus_hour(iso: str) -> str:
    try:
        return (datetime.fromisoformat(iso) + timedelta(hours=1)).isoformat()
    except ValueError:
        return iso


def _fmt_when(start: str, end: str) -> str:
    try:
        s = datetime.fromisoformat(start)
        e = datetime.fromisoformat(end)
        return f"{s.strftime('%a %b %d, %H:%M')}–{e.strftime('%H:%M')}"
    except ValueError:
        return start


def stage_event_item(event: dict) -> int:
    """Stage a proposed calendar PlanItem (op=create). Returns the item id."""
    from db import session_scope
    from models import PlanItem
    from planner import today_str

    payload = {
        "op": "create",
        "summary": event["summary"],
        "start": event["start"],
        "end": event.get("end") or _plus_hour(event["start"]),
    }
    with session_scope() as s:
        item = PlanItem(day=today_str(), kind="calendar", title=event["summary"],
                        payload_json=json.dumps(payload))
        s.add(item)
        s.commit()
        s.refresh(item)
        return item.id


def event_card(event: dict, item_id: int):
    """Build the 'Add to calendar?' approval Card for an extracted event."""
    from dispatch.cards import Card, Action

    when = _fmt_when(event["start"], event.get("end") or _plus_hour(event["start"]))
    return Card(
        headline="Add to calendar?",
        lines=[f"{event['summary']} · {when}"],
        actions=[Action("Approve", f"approve:{item_id}"),
                 Action("Edit", f"op:edit:{item_id}"),
                 Action("Skip", f"reject:{item_id}")],
    )


def handle_converse(text: str, chat_id: int, *, context: str = "") -> dict:
    """Run the conversational lane and send the reply (+ an approval card if the
    message contained a calendar event). Safe to run in a background thread."""
    from dispatch import dispatcher
    from dispatch.telegram_format import format_telegram
    from dispatch.cards import send_card

    res = converse(text, context=context)
    dispatcher.send_telegram_message(chat_id, format_telegram(res["reply"]))
    if res.get("event"):
        item_id = stage_event_item(res["event"])
        send_card(chat_id, event_card(res["event"], item_id))
        return {"ok": True, "status": "converse_event", "item_id": item_id}
    return {"ok": True, "status": "converse"}
