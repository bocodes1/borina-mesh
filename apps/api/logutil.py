"""Timestamp prefix for the plain `print(f"[module] ...")` log lines used
across scheduler/operator/learner modules — those had no time information at
all, which turned a one-line agent-id bug into a multi-week grep-the-log
investigation (see operator_brain.py history). Not a logging-framework
migration, just enough to make these lines time-bounded."""
from __future__ import annotations

from datetime import datetime, timezone


def log_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
