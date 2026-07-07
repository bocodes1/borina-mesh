"""Deskview / cex-lag-bot watcher — NON-LLM, zero cost.

Reads the trading bot's own SQLite log (read-only) every scheduler tick and
messages Bo only on state *transitions*, never on steady state:

- heartbeat: the bot writes a `trade_attempts` row on every evaluation tick;
  silence > 1h → one "bot down" alert, recovery → one "bot back" alert.
- fills: a new resolved fill (win or loss) → one summary line.
- runway: v2 cumulative net vs the bot's −$15 kill switch; one alert when the
  remaining runway first crosses below $5, another below $2.50.

State lives in ~/.borina/deskview_alerts_state.json so restarts don't
re-alert. Missing bot DB → inert (safe in dev/CI and on other machines).
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB = Path.home() / "Desktop" / "cex-lag-bot" / "data" / "live_test.db"
STATE_PATH = Path.home() / ".borina" / "deskview_alerts_state.json"

V2_SWITCH_UNIX = datetime(2026, 7, 2, tzinfo=timezone.utc).timestamp()
KILL_SWITCH_USD = float(os.getenv("DESKVIEW_KILL_SWITCH_USD", "15"))
RED_AFTER_S = 3600
RUNWAY_STEPS = (5.0, 2.5)  # alert when remaining runway first drops below each


def _bot_db_path() -> Path:
    return Path(os.getenv("CEXLAG_DB") or DEFAULT_DB).expanduser()


def read_snapshot(db_path: Path) -> dict | None:
    """One cheap read-only pass over the bot DB; None when unreadable."""
    if not db_path.exists():
        return None
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0)
        try:
            last_tick = con.execute(
                "SELECT MAX(timestamp_unix) FROM trade_attempts"
            ).fetchone()[0]
            fills, v2_net = con.execute(
                """SELECT COUNT(*), COALESCE(SUM(CASE WHEN timestamp_unix >= ?
                                                      THEN pnl_net ELSE 0 END), 0)
                   FROM trade_attempts
                   WHERE fill_status = 'filled' AND won IS NOT NULL""",
                (V2_SWITCH_UNIX,),
            ).fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        return None
    return {"last_tick": last_tick, "fills": fills, "v2_net": v2_net}


def evaluate(snapshot: dict, state: dict, now: float) -> tuple[list[str], dict]:
    """Pure transition logic: (alerts to send, next state). First run only
    baselines — it never alerts on pre-existing conditions."""
    alerts: list[str] = []
    first_run = not state

    # -- heartbeat ---------------------------------------------------------
    last_tick = snapshot["last_tick"]
    age = now - last_tick if last_tick is not None else None
    status = "red" if age is None or age > RED_AFTER_S else "green"
    prev_status = state.get("status")
    if not first_run and status != prev_status:
        if status == "red":
            since = datetime.fromtimestamp(last_tick, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
            alerts.append(
                f"🔴 cex-lag bot looks DOWN — no evaluation ticks for {age / 3600:.1f}h (last {since} UTC)."
            )
        elif prev_status == "red":
            alerts.append("🟢 cex-lag bot is back — evaluation ticks resumed.")

    # -- new resolved fills --------------------------------------------------
    fills = snapshot["fills"]
    prev_fills = state.get("fills")
    if not first_run and prev_fills is not None and fills > prev_fills:
        n = fills - prev_fills
        alerts.append(
            f"📊 {n} new resolved fill{'s' if n != 1 else ''} (total {fills}) — v2 net ${snapshot['v2_net']:+.2f}."
        )

    # -- runway --------------------------------------------------------------
    remaining = max(0.0, KILL_SWITCH_USD + min(0.0, snapshot["v2_net"]))
    bucket = sum(1 for step in RUNWAY_STEPS if remaining < step)
    prev_bucket = state.get("runway_bucket", 0)
    if not first_run and bucket > prev_bucket:
        alerts.append(
            f"⚠️ v2 drawdown runway is ${remaining:.2f} — "
            f"${KILL_SWITCH_USD + min(0.0, snapshot['v2_net']):.2f} of the −${KILL_SWITCH_USD:.0f} kill switch left."
        )

    return alerts, {"status": status, "fills": fills, "runway_bucket": bucket}


def run(db_path: Path | None = None, state_path: Path | None = None, now: float | None = None) -> list[str]:
    """Read → evaluate → persist. Returns the alert lines to send."""
    db_path = db_path or _bot_db_path()
    state_path = state_path or STATE_PATH
    snapshot = read_snapshot(db_path)
    if snapshot is None:
        return []  # nothing to watch — stay silent and keep old state
    state: dict = {}
    try:
        state = json.loads(state_path.read_text())
    except (OSError, ValueError):
        pass
    alerts, new_state = evaluate(snapshot, state, now if now is not None else time.time())
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(new_state))
    except OSError as e:  # keep alerting even if state can't persist
        print(f"[deskview-alerts] state write failed: {e}")
    return alerts
