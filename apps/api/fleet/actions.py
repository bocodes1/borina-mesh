"""Fleet actions (L4) — park / reactivate. Idempotent; safe to call repeatedly.

Park is reversible (the only auto action). Retire is NEVER automatic — it is a
human-confirmed callback in routes/telegram.py.
"""
from __future__ import annotations

# Default crons mirror scheduler.register_defaults so reactivation restores cadence.
_DEFAULT_CRONS = {
    "ceo": "0 7 * * *",
    "ecommerce-scout": "0 8 * * *",
    "polymarket-intel": "0 8 * * *",
    "researcher": "0 8 * * *",
    "adset-optimizer": "0 17 * * *",
    "trader": "*/30 * * * *",
    "inbox-triage": "0 */2 * * *",
}


def park_agent(agent_id: str) -> dict:
    """Flip the agent to parked and drop its schedule. Idempotent."""
    from fleet_roster import set_state, canonical, PARKED
    long_id = canonical(agent_id)
    set_state(long_id, PARKED)
    try:
        from scheduler import scheduler_service
        scheduler_service.remove_schedule(long_id)
    except Exception:  # noqa: BLE001
        pass
    return {"agent": long_id, "state": PARKED}


def reactivate_agent(agent_id: str) -> dict:
    """Flip the agent back to active and restore its default schedule. Idempotent."""
    from fleet_roster import set_state, canonical, ACTIVE
    long_id = canonical(agent_id)
    set_state(long_id, ACTIVE)
    cron = _DEFAULT_CRONS.get(long_id)
    if cron:
        try:
            from scheduler import scheduler_service
            scheduler_service.set_schedule(long_id, cron)
        except Exception:  # noqa: BLE001
            pass
    return {"agent": long_id, "state": ACTIVE, "cron": cron}
