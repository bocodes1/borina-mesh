"""Job priority bands (L4). Higher runs first; FIFO within a band."""
from __future__ import annotations

USER = 100        # a real Telegram ask / a /jobs create
FOLLOW_UP = 90    # reply-to-report thread follow-up
INTERNAL = 60     # operator/fleet internal work
SCHEDULED = 50    # cron-driven agent run (the default)
SWEEP = 10        # backfill / health sweep


def priority_for(kind: str, *, source: str = "") -> int:
    """Map a job's kind/source to a priority band."""
    if source == "follow_up":
        return FOLLOW_UP
    if kind == "telegram_dispatch" or source == "user":
        return USER
    if source in ("operator", "fleet"):
        return INTERNAL
    if source == "sweep":
        return SWEEP
    return SCHEDULED
