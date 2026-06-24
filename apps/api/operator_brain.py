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
