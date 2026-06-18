"""Free/busy gap-finding for the daily operator (L2).

Replaces the hardcoded 09:00–11:00 focus block with a real gap computed from the
calendar's busy intervals, in America/New_York. Pure + testable: the calendar
fetch is injected so tests don't hit Google.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    _TZ = None


def _parse(dt: str) -> datetime:
    d = datetime.fromisoformat(dt.replace("Z", "+00:00"))
    if d.tzinfo is None and _TZ is not None:
        d = d.replace(tzinfo=_TZ)
    return d


def find_gaps(
    busy: list[dict],
    *,
    day: Optional[datetime] = None,
    min_minutes: int = 120,
    work_start: int = 9,
    work_end: int = 18,
) -> Optional[dict]:
    """Given busy intervals [{start,end}] (RFC3339), return the first free gap of
    at least `min_minutes` inside the work window, as {start, end} ISO strings, or
    None if there's no qualifying gap.

    `day` defaults to today in America/New_York; pass it in tests for determinism.
    """
    if day is None:
        day = datetime.now(_TZ) if _TZ else datetime.now()
    base = day.replace(hour=work_start, minute=0, second=0, microsecond=0)
    window_end = day.replace(hour=work_end, minute=0, second=0, microsecond=0)

    def _align(d: datetime) -> datetime:
        # Make d's tz-awareness match the window so comparisons don't blow up.
        if base.tzinfo is None:
            return d.replace(tzinfo=None)
        return d if d.tzinfo is not None else d.replace(tzinfo=base.tzinfo)

    intervals = []
    for b in busy:
        try:
            s, e = _align(_parse(b["start"])), _align(_parse(b["end"]))
        except Exception:
            continue
        # clip to the work window
        s = max(s, base)
        e = min(e, window_end)
        if e > s:
            intervals.append((s, e))
    intervals.sort()

    need = timedelta(minutes=min_minutes)
    cursor = base
    for s, e in intervals:
        if s - cursor >= need:
            return {"start": cursor.isoformat(), "end": (cursor + need).isoformat()}
        cursor = max(cursor, e)
    if window_end - cursor >= need:
        return {"start": cursor.isoformat(), "end": (cursor + need).isoformat()}
    return None
