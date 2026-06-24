"""Nightly learner (L2.5) — a durable model of Bo built from the day's signals.

Runs in the eod operator phase. READS today's daily note, the Telegram
conversation log, and tasks/calendar; has the `planner` agent rewrite a bounded
`operator-profile.md` in the vault. Text-only — stages nothing, writes only the
profile file. The mesh's approve-only calendar invariant is untouched.
"""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Optional

_PROFILE_FILE = ("04-resources", "brain", "operator-profile.md")
_SECTIONS = (
    "## Active threads",
    "## Recurring priorities",
    "## Working rhythms",
    "## Preferences",
    "## Recently completed / closed",
)

EMPTY_PROFILE = """# Operator profile — Bo
_Updated: never_

## Active threads

## Recurring priorities

## Working rhythms

## Preferences

## Recently completed / closed
"""


def _vault() -> Optional[Path]:
    root = os.getenv("OBSIDIAN_VAULT_PATH", "").strip()
    if not root:
        return None
    p = Path(root)
    return p if p.is_dir() else None


def _profile_path() -> Optional[Path]:
    v = _vault()
    return v.joinpath(*_PROFILE_FILE) if v else None


def read_profile() -> str:
    """Current profile text, or EMPTY_PROFILE (no vault / not yet written)."""
    p = _profile_path()
    if p and p.exists():
        try:
            return p.read_text()
        except OSError:
            return EMPTY_PROFILE
    return EMPTY_PROFILE


def _is_valid_profile(text: str) -> bool:
    """Non-trivial and carries every fixed section — guards against overwriting
    good state with a truncated/garbage agent reply."""
    if not text or len(text.strip()) < 40:
        return False
    return all(sec in text for sec in _SECTIONS)


def write_profile(text: str) -> Optional[Path]:
    """Write the profile back. Returns the path, or None (no vault / invalid)."""
    p = _profile_path()
    if not p or not _is_valid_profile(text):
        return None
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p
    except OSError:
        return None


def _count_active_threads(text: str) -> int:
    """Number of bullet lines under '## Active threads'."""
    lines = text.splitlines()
    try:
        start = next(i for i, l in enumerate(lines) if l.strip() == "## Active threads")
    except StopIteration:
        return 0
    n = 0
    for l in lines[start + 1:]:
        if l.startswith("## "):
            break
        if l.strip().startswith("- "):
            n += 1
    return n


# ── signals + nightly learner ────────────────────────────────────────────────

def _today_daily_note(day: str) -> str:
    v = _vault()
    if not v:
        return ""
    note = v / "01-daily" / f"{day}.md"
    try:
        return note.read_text()[:4000] if note.exists() else ""
    except OSError:
        return ""


def _task_signal(day: str) -> dict:
    from sqlmodel import select
    from db import session_scope
    from models import Task
    with session_scope() as s:
        tasks = s.exec(select(Task)).all()
        created_today = [t.title for t in tasks if t.created_at.date().isoformat() == day]
        open_titles = [t.title for t in tasks if not t.done][:20]
    return {"created_today": created_today, "open": open_titles}


def _calendar_signal(day: str) -> list[dict]:
    from integrations import google_calendar
    cal = google_calendar.list_events(f"{day}T00:00:00Z", f"{day}T23:59:59Z")
    events = cal.data if cal.connected else []
    return [{"title": e.get("title"), "start": e.get("start")} for e in events]


def _gather_signals(day: str) -> dict:
    from conversation_log import recent_for_day
    convo = recent_for_day(day)
    cal = _calendar_signal(day)  # one calendar call, not two
    return {
        "daily_note": _today_daily_note(day) or "(none)",
        "conversation": json.dumps(convo)[:4000] if convo else "(none)",
        "tasks": json.dumps(_task_signal(day)),
        "calendar": json.dumps(cal) if cal else "(none)",
    }


LEARNER_PROMPT = """<task name="update_operator_profile">
You maintain a durable PROFILE of Bo — a compressed model of what he is working
on and how he likes his days. Today is {day}. Update the profile from today's
signals. Output ONLY the full updated profile markdown (no prose, no code fences).

Rules:
- Keep the EXACT section headers, in this order: "# Operator profile — Bo",
  "## Active threads", "## Recurring priorities", "## Working rhythms",
  "## Preferences", "## Recently completed / closed".
- Set the line under the title to "_Updated: {day} (eod)_".
- Each section is a bounded bullet list (max 10 bullets). Prune the oldest/stale.
- "## Active threads" bullets END with " — last touched <YYYY-MM-DD>". Refresh that
  date for any thread today's signals touched. Move a thread untouched for more
  than 7 days into "## Recently completed / closed" as a one-line note.
- NO invention. Only assert what the signals or the prior profile support. Prefer
  FRESH items from today; do not re-add finished work.

Prior profile:
---
{profile}
---

Today's signals:
- Daily note: {daily_note}
- Telegram conversation (role/text JSON): {conversation}
- Tasks (created_today / open JSON): {tasks}
- Calendar events JSON: {calendar}
</task>"""


async def _call_agent(prompt: str) -> str:
    """Run the learner prompt through the planner agent (chief-of-staff persona).
    Returns the agent's text output ("" on failure)."""
    from agents.runner_v2 import run_agent_task
    result = await run_agent_task("planner", prompt)
    return getattr(result, "output", None) or ""


async def update_profile(day: Optional[str] = None) -> dict:
    """The nightly learner. Reads the day's signals + current profile, has the
    agent emit an updated profile, validates it, and writes it back — keeping the
    old profile on ANY failure. Then trims the conversation log. Text-only."""
    day = day or date.today().isoformat()
    current = read_profile()
    try:
        prompt = LEARNER_PROMPT.format(day=day, profile=current, **_gather_signals(day))
        candidate = await _call_agent(prompt)
    except Exception as exc:  # noqa: BLE001
        print(f"[operator_brain] learner failed: {exc}")
        candidate = ""

    written = bool(_is_valid_profile(candidate) and write_profile(candidate))

    from conversation_log import trim_older_than
    trimmed = trim_older_than(30)

    return {
        "day": day,
        "written": written,
        "active_threads": _count_active_threads(read_profile()),
        "trimmed": trimmed,
    }
