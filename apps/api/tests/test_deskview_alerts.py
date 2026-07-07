"""Deskview/cex-lag-bot watcher — transition-only alerting, hermetic."""
import json
import sqlite3
from datetime import datetime, timezone

import pytest

from agents import deskview_alerts as da

V2 = datetime(2026, 7, 2, tzinfo=timezone.utc).timestamp()
NOW = V2 + 5 * 86400


def make_bot_db(path, last_tick, fills=()):
    """fills: iterable of (timestamp_unix, pnl_net)."""
    con = sqlite3.connect(path)
    con.execute(
        """CREATE TABLE trade_attempts (
             timestamp_unix REAL, fill_status TEXT, won INTEGER, pnl_net REAL)"""
    )
    con.execute("INSERT INTO trade_attempts VALUES (?, NULL, NULL, NULL)", (last_tick,))
    for ts, pnl in fills:
        con.execute(
            "INSERT INTO trade_attempts VALUES (?, 'filled', ?, ?)",
            (ts, 1 if pnl > 0 else 0, pnl),
        )
    con.commit()
    con.close()
    return path


@pytest.fixture()
def paths(tmp_path):
    return tmp_path / "bot.db", tmp_path / "state.json"


def test_missing_db_is_inert(paths):
    db, state = paths
    assert da.run(db_path=db, state_path=state, now=NOW) == []
    assert not state.exists()


def test_first_run_baselines_without_alerting(paths):
    db, state = paths
    make_bot_db(db, last_tick=NOW - 90000, fills=[(V2 + 100, -1.0)])  # already down
    assert da.run(db_path=db, state_path=state, now=NOW) == []
    saved = json.loads(state.read_text())
    assert saved["status"] == "red" and saved["fills"] == 1


def test_down_transition_alerts_once(paths):
    db, state = paths
    make_bot_db(db, last_tick=NOW - 60)
    assert da.run(db_path=db, state_path=state, now=NOW) == []  # green baseline
    late = NOW + 2 * 3600
    first = da.run(db_path=db, state_path=state, now=late)
    assert len(first) == 1 and "DOWN" in first[0]
    assert da.run(db_path=db, state_path=state, now=late + 600) == []  # no re-alert


def test_recovery_alerts(paths):
    db, state = paths
    make_bot_db(db, last_tick=NOW - 90000)
    da.run(db_path=db, state_path=state, now=NOW)  # baseline red
    db.unlink()
    make_bot_db(db, last_tick=NOW + 100)
    alerts = da.run(db_path=db, state_path=state, now=NOW + 200)
    assert len(alerts) == 1 and "back" in alerts[0]


def test_new_fill_alerts_with_v2_net(paths):
    db, state = paths
    make_bot_db(db, last_tick=NOW, fills=[(V2 - 86400, -3.91)])  # v1 fill only
    da.run(db_path=db, state_path=state, now=NOW)
    db.unlink()
    make_bot_db(db, last_tick=NOW, fills=[(V2 - 86400, -3.91), (NOW - 60, -1.0)])
    alerts = da.run(db_path=db, state_path=state, now=NOW)
    assert len(alerts) == 1
    assert "1 new resolved fill" in alerts[0] and "-1.00" in alerts[0]


def test_runway_crossing_alerts_once_per_step(paths):
    db, state = paths
    make_bot_db(db, last_tick=NOW, fills=[(NOW - 300, -8.5)])  # runway 6.50
    da.run(db_path=db, state_path=state, now=NOW)
    db.unlink()
    make_bot_db(db, last_tick=NOW, fills=[(NOW - 300, -8.5), (NOW - 60, -2.0)])  # 4.50
    alerts = da.run(db_path=db, state_path=state, now=NOW)
    assert any("runway" in a for a in alerts)
    assert da.run(db_path=db, state_path=state, now=NOW) == []  # steady state silent


@pytest.mark.asyncio
async def test_scheduler_sends_alerts_via_telegram(monkeypatch, paths, tmp_path):
    db, state = paths
    make_bot_db(db, last_tick=NOW - 60)
    monkeypatch.setattr(da, "STATE_PATH", state)
    monkeypatch.setenv("CEXLAG_DB", str(db))
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    import time as _time
    monkeypatch.setattr(_time, "time", lambda: NOW)

    from dispatch import dispatcher
    sent = []
    monkeypatch.setattr(dispatcher, "send_telegram_message", lambda c, t, **k: sent.append(t) or 1)

    from scheduler import SchedulerService
    svc = SchedulerService()
    await svc._run_deskview_alerts()  # baseline, green
    assert sent == []
    monkeypatch.setattr(_time, "time", lambda: NOW + 2 * 3600)
    await svc._run_deskview_alerts()
    assert len(sent) == 1 and "DOWN" in sent[0]
