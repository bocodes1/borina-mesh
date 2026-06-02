"""Daily-brief artifact: section parser + load/save helpers (spec §8).

`schedule_daily` writes `reports/{today}/daily-brief.md` containing the
sections defined by the task prompt, each wrapped as:

    <section id="tldr">
    ...markdown...
    </section>

The Finance / Daily / Calendar tabs each read the sections they care about,
parsed by id here so there's one source of truth for the format.
"""
from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path
from typing import Optional

# Canonical section order the brief is written in.
SECTION_IDS = [
    "tldr",
    "markets",
    "watchlist_movers",
    "trading",
    "calendar",
    "tasks_focus",
    "inbox",
    "nudges",
    "weather_logistics",
]

_SECTION_RE = re.compile(
    r'<section\s+id="(?P<id>[a-z_]+)"\s*>(?P<body>.*?)</section>',
    re.DOTALL | re.IGNORECASE,
)


def parse_brief(markdown: str) -> dict[str, str]:
    """Split a brief's markdown into {section_id: body}. Unknown ids are kept;
    missing sections are simply absent (callers handle empties)."""
    return {m.group("id").lower(): m.group("body").strip() for m in _SECTION_RE.finditer(markdown)}


def today_str() -> str:
    return date.today().isoformat()


def _reports_root() -> Path:
    return Path(os.getenv("REPORTS_DIR", "./reports")).resolve()


def brief_path(day: Optional[str] = None) -> Path:
    return _reports_root() / (day or today_str()) / "daily-brief.md"


def save_brief(markdown: str, day: Optional[str] = None) -> Path:
    """Write the brief to reports/{day}/daily-brief.md (creating dirs)."""
    path = brief_path(day)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown)
    return path


def load_brief(day: Optional[str] = None) -> Optional[dict]:
    """Return {date, raw, sections} for the given day's brief, or None if absent."""
    path = brief_path(day)
    if not path.exists():
        return None
    raw = path.read_text()
    return {"date": day or today_str(), "raw": raw, "sections": parse_brief(raw)}


def sections_for(day: Optional[str], ids: list[str]) -> dict[str, Optional[str]]:
    """Return only the requested section ids (value None when missing/absent)."""
    brief = load_brief(day)
    sections = brief["sections"] if brief else {}
    return {sid: sections.get(sid) for sid in ids}
