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

from logutil import log_ts

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
    """created_today/open — same as before — plus completed_today, now possible
    because Task.completed_at (Phase D1) actually timestamps the done
    transition. Before this, a task finished today and one finished three
    weeks ago both just vanished from "open" with no way to tell them apart."""
    from sqlmodel import select
    from db import session_scope
    from models import Task
    with session_scope() as s:
        tasks = s.exec(select(Task)).all()
        created_today = [t.title for t in tasks if t.created_at.date().isoformat() == day]
        open_titles = [t.title for t in tasks if not t.done][:20]
        completed_today = [
            t.title for t in tasks
            if t.done and t.completed_at and t.completed_at.date().isoformat() == day
        ]
    return {"created_today": created_today, "open": open_titles, "completed_today": completed_today}


def _calendar_signal(day: str) -> list[dict]:
    from integrations import google_calendar
    cal = google_calendar.list_events(f"{day}T00:00:00Z", f"{day}T23:59:59Z")
    events = cal.data if cal.connected else []
    return [{"title": e.get("title"), "start": e.get("start")} for e in events]


def _gather_signals(day: str) -> dict:
    from conversation_log import recent_for_day
    convo = recent_for_day(day)
    cal = _calendar_signal(day)  # one calendar call, not two
    tasks = _task_signal(day)
    return {
        "daily_note": _today_daily_note(day) or "(none)",
        "conversation": json.dumps(convo)[:4000] if convo else "(none)",
        "tasks": json.dumps(tasks),
        "calendar": json.dumps(cal) if cal else "(none)",
        "task_titles": (tasks.get("open", [])[:5] + tasks.get("created_today", [])[:3]
                        + tasks.get("completed_today", [])[:3]),
        "event_titles": [e.get("title") for e in cal if e.get("title")],
    }


LEARNER_PROMPT = """<task name="update_operator_profile">
You maintain a durable PROFILE of Bo — a compressed model of what he is working
on and how he likes his days. Today is {day}. Update the profile from today's
signals (daily note, Telegram conversation, tasks, calendar — below under
CONTEXT). Output ONLY the full updated profile markdown (no prose, no code fences).

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
- The tasks signal's "completed_today" list is real, timestamped completions —
  not an inference. Use it directly for "## Recently completed / closed" instead
  of guessing from what dropped out of "open".
- The Telegram conversation includes entries with role="correction" — Bo
  explicitly wrote these for you, not ambient chat. Treat them as ground truth
  that overrides any conflicting inference from other signals or the prior
  profile.

Prior profile:
---
{profile}
---
</task>"""


async def _call_agent(prompt: str) -> str:
    """Run the learner prompt through the planner agent (chief-of-staff persona).
    Returns the agent's text output ("" on failure)."""
    from agents.runner_v2 import run_agent_task
    result = await run_agent_task("operator", prompt)
    return getattr(result, "output", None) or ""


async def update_profile(day: Optional[str] = None) -> dict:
    """The nightly learner. Reads the day's signals + current profile, has the
    agent emit an updated profile, validates it, and writes it back — keeping the
    old profile on ANY failure. Then trims the conversation log. Text-only."""
    day = day or date.today().isoformat()
    current = read_profile()
    try:
        from agents.context_pack import build_context_pack, adaptive_query
        from agents.contracts import last_artifact_text
        signals = _gather_signals(day)
        prompt = LEARNER_PROMPT.format(day=day, profile=current)
        data = (
            f"Daily note: {signals['daily_note']}\n"
            f"Telegram conversation (role/text JSON): {signals['conversation']}\n"
            f"Tasks (created_today / open JSON): {signals['tasks']}\n"
            f"Calendar events JSON: {signals['calendar']}"
        )
        query = adaptive_query("operator profile day recap",
                                signals["task_titles"], signals["event_titles"])
        pack = build_context_pack("operator", query=query, data=data,
                                  last_artifact=last_artifact_text("operator"))
        prompt = f"{prompt}\n\nCONTEXT:\n{pack.text}"
        candidate = await _call_agent(prompt)
    except Exception as exc:  # noqa: BLE001
        print(f"{log_ts()} [operator_brain] learner failed: {exc}")
        candidate = ""

    written = bool(_is_valid_profile(candidate) and write_profile(candidate))
    if not written:
        print(f"{log_ts()} [operator_brain] learner produced invalid/empty profile "
              f"({len(candidate)} chars) — kept prior")

    from conversation_log import trim_older_than
    trimmed = trim_older_than(30)

    return {
        "day": day,
        "written": written,
        "active_threads": _count_active_threads(read_profile()),
        "trimmed": trimmed,
    }
