"""Fleet roster — the source of truth for which agents are active.

Foundation slice §A. Promotes the (previously dead) `AgentConfig` table into the
authoritative roster with a lifecycle state:

  active   — routable by intent, schedulable, shown in /help and /fleet
  parked   — NOT scheduled, NOT auto-routed, hidden from /help; still summonable
             by explicit name ("adset: …") so it reactivates on demand
  retired  — gone from routing/scheduling entirely

It also bridges the two id-spaces: intent uses short aliases (`inbox`, `scout`),
the registry + scheduler use long ids (`inbox-triage`, `ecommerce-scout`). The
roster is keyed by the long (canonical) id.
"""
from __future__ import annotations

from typing import Optional

from sqlmodel import Session, select

# short alias (intent) -> long canonical id (registry/scheduler).
SHORT_TO_LONG = {
    "ceo": "ceo",
    "trader": "trader",
    "researcher": "researcher",
    "scout": "ecommerce-scout",
    "polymarket": "polymarket-intel",
    "adset": "adset-optimizer",
    "inbox": "inbox-triage",
    "finance": "finance",
    "planner": "planner",
}
LONG_TO_SHORT = {v: k for k, v in SHORT_TO_LONG.items()}

ACTIVE, PARKED, RETIRED = "active", "parked", "retired"

# The decided lean roster (keyed by canonical long id). Anything not listed
# defaults to active so a newly-added agent routes until explicitly parked.
ROSTER_SEED: dict[str, str] = {
    "trader": ACTIVE,
    "inbox-triage": ACTIVE,
    "ceo": ACTIVE,
    "researcher": ACTIVE,
    "adset-optimizer": PARKED,
    "ecommerce-scout": PARKED,
    "polymarket-intel": RETIRED,
    "qa_director": RETIRED,
    "finance": RETIRED,
    "planner": RETIRED,
    "polymarket": RETIRED,   # legacy duplicate id
    "curator": RETIRED,
}


def canonical(agent_id: str) -> str:
    """Normalize a short alias to its long canonical id (id-space bridge)."""
    return SHORT_TO_LONG.get(agent_id, agent_id)


def ensure_state_column(engine) -> None:
    """Add AgentConfig.state to an existing DB that predates it (SQLite ALTER).
    The table is created by init_db; this only patches a legacy schema."""
    from sqlalchemy import text
    with engine.connect() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(agentconfig)"))}
        if cols and "state" not in cols:
            conn.execute(text("ALTER TABLE agentconfig ADD COLUMN state VARCHAR DEFAULT 'active'"))
            conn.commit()


def seed_roster(engine) -> int:
    """Idempotently seed AgentConfig from ROSTER_SEED. Existing rows are NOT
    clobbered (a state the user changed via /fleet wins). Returns rows added."""
    from sqlmodel import SQLModel
    from models import AgentConfig  # registers the model
    # Ensure the table exists (idempotent) before seeding — important when this
    # runs before a full init_db (e.g. isolated tests).
    SQLModel.metadata.create_all(engine, tables=[AgentConfig.__table__])
    ensure_state_column(engine)
    added = 0
    with Session(engine) as s:
        for long_id, state in ROSTER_SEED.items():
            row = s.get(AgentConfig, long_id)
            if row is None:
                s.add(AgentConfig(agent_id=long_id, state=state, enabled=(state != RETIRED)))
                added += 1
            elif getattr(row, "state", None) in (None, ""):
                # legacy row with no state yet — backfill, keep everything else.
                row.state = state
                s.add(row)
        s.commit()
    return added


def get_state(agent_id: str) -> str:
    """Lifecycle state for an agent (accepts short or long id). Unknown → active."""
    from db import engine
    from models import AgentConfig
    long_id = canonical(agent_id)
    with Session(engine) as s:
        row = s.get(AgentConfig, long_id)
        if row is not None and getattr(row, "state", None):
            return row.state
    return ROSTER_SEED.get(long_id, ACTIVE)


def is_routable(agent_id: str, *, direct: bool = False) -> bool:
    """Can intent route to this agent? Active always; parked only via an explicit
    `<agent>:` address (direct); retired never."""
    state = get_state(agent_id)
    if state == ACTIVE:
        return True
    if state == PARKED:
        return direct
    return False


def set_state(agent_id: str, state: str) -> None:
    from db import engine
    from models import AgentConfig
    long_id = canonical(agent_id)
    with Session(engine) as s:
        row = s.get(AgentConfig, long_id)
        if row is None:
            row = AgentConfig(agent_id=long_id)
        row.state = state
        row.enabled = state != RETIRED
        s.add(row)
        s.commit()


def list_roster() -> list[dict]:
    """Roster for /fleet: every non-retired agent with its state + short alias."""
    from db import engine
    from models import AgentConfig
    out: list[dict] = []
    with Session(engine) as s:
        rows = {r.agent_id: r for r in s.exec(select(AgentConfig)).all()}
    seen = set()
    for long_id, default_state in ROSTER_SEED.items():
        state = getattr(rows.get(long_id), "state", None) or default_state
        seen.add(long_id)
        if state == RETIRED:
            continue
        out.append({"id": long_id, "short": LONG_TO_SHORT.get(long_id, long_id), "state": state})
    for long_id, row in rows.items():
        if long_id in seen:
            continue
        if (row.state or ACTIVE) != RETIRED:
            out.append({"id": long_id, "short": LONG_TO_SHORT.get(long_id, long_id), "state": row.state or ACTIVE})
    return sorted(out, key=lambda d: (d["state"] != ACTIVE, d["id"]))


def active_scheduled_agents(default_schedules: dict[str, str]) -> dict[str, str]:
    """Filter a {long_id: cron} map down to agents whose roster state is active."""
    return {aid: cron for aid, cron in default_schedules.items() if get_state(aid) == ACTIVE}
