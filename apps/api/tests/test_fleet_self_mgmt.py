"""L4 fleet self-management — priority queue, health checks, park/retire flow."""
from datetime import datetime, timedelta

import pytest

from fleet.priority import priority_for, USER, SCHEDULED, FOLLOW_UP, SWEEP
from fleet import health, actions, cards


@pytest.fixture(autouse=True)
def _seed():
    from db import engine
    import fleet_roster as fr
    fr.seed_roster(engine)
    yield


# ── priority bands ─────────────────────────────────────────────────────────────
def test_priority_bands():
    assert priority_for("telegram_dispatch") == USER
    assert priority_for("agent_run", source="follow_up") == FOLLOW_UP
    assert priority_for("agent_run") == SCHEDULED
    assert priority_for("agent_run", source="sweep") == SWEEP
    assert USER > FOLLOW_UP > SCHEDULED > SWEEP


def test_worker_claims_high_priority_first():
    from dispatch import worker
    from db import session_scope
    from models import Job, JobStatus
    with session_scope() as s:
        # older low-priority scheduled job
        s.add(Job(agent_id="trader", prompt="cron", kind="telegram_dispatch",
                  status=JobStatus.QUEUED, priority=50,
                  created_at=datetime.utcnow() - timedelta(minutes=10)))
        # newer high-priority user job
        s.add(Job(agent_id="ceo", prompt="user", kind="telegram_dispatch",
                  status=JobStatus.QUEUED, priority=100))
        s.commit()
    claimed = worker.claim_next()
    assert claimed.agent_id == "ceo"      # high priority jumps the older one


# ── health checks ──────────────────────────────────────────────────────────────
def test_idle_agents_flags_stale_active_agent():
    from db import engine, session_scope
    from models import Job, JobStatus
    now = datetime.utcnow()
    # trader ran recently; researcher long ago.
    with session_scope() as s:
        s.add(Job(agent_id="trader", prompt="x", status=JobStatus.COMPLETED, created_at=now - timedelta(hours=1)))
        s.add(Job(agent_id="researcher", prompt="x", status=JobStatus.COMPLETED, created_at=now - timedelta(days=30)))
        s.commit()
    findings = health.idle_agents(engine, now=now, days=7)
    idle = {f["agent"] for f in findings}
    assert "researcher" in idle
    assert "trader" not in idle


def test_failing_agents_flags_high_failure_rate():
    from db import engine, session_scope
    from models import Job, JobStatus
    now = datetime.utcnow()
    with session_scope() as s:
        for _ in range(4):
            s.add(Job(agent_id="ceo", prompt="x", status=JobStatus.FAILED, created_at=now - timedelta(hours=1)))
        for _ in range(2):
            s.add(Job(agent_id="ceo", prompt="x", status=JobStatus.COMPLETED, created_at=now - timedelta(hours=1)))
        s.commit()
    findings = health.failing_agents(engine, now=now)
    assert any(f["agent"] == "ceo" for f in findings)   # 4/6 failed ≥ 0.5


def test_orphaned_jobs_flags_long_running():
    from db import engine, session_scope
    from models import Job, JobStatus
    now = datetime.utcnow()
    with session_scope() as s:
        s.add(Job(agent_id="trader", prompt="x", kind="telegram_dispatch",
                  status=JobStatus.RUNNING, started_at=now - timedelta(hours=5)))
        s.commit()
    findings = health.orphaned_jobs(engine, now=now)
    assert any(f["kind"] == "orphan" for f in findings)


# ── actions ──────────────────────────────────────────────────────────────────
def test_park_and_reactivate_flip_state():
    import fleet_roster as fr
    actions.park_agent("trader")
    assert fr.get_state("trader") == fr.PARKED
    actions.reactivate_agent("trader")
    assert fr.get_state("trader") == fr.ACTIVE


# ── cards ────────────────────────────────────────────────────────────────────
def test_health_card_lists_findings_and_offers_buttons():
    findings = [
        {"kind": "idle", "agent": "researcher", "severity": "warn", "detail": "no run in 7d"},
        {"kind": "failing", "agent": "ceo", "severity": "alert", "detail": "4/6 failed in 7d"},
    ]
    card = cards.health_card(findings)
    datas = [a.data for a in card.actions]
    assert any(d.startswith("park:") for d in datas)
    assert any(d.startswith("retire:") for d in datas)


def test_health_card_all_green():
    card = cards.health_card([])
    assert "green" in card.lines[0].lower()


# ── retire is never automatic: propose → confirm ──────────────────────────────
def test_retire_requires_confirmation(monkeypatch):
    import routes.telegram as tg
    from dispatch import dispatcher
    import fleet_roster as fr
    sent = []
    monkeypatch.setattr(dispatcher, "send_telegram_message", lambda c, t, **k: sent.append(t) or 1)
    monkeypatch.setattr("dispatch.cards.send_card", lambda c, card: sent.append(card.headline) or 1)

    # propose: does NOT change state
    tg._handle_callback("retire:trader", 99)
    assert fr.get_state("trader") == fr.ACTIVE
    # confirm: now retired
    tg._handle_callback("retireconfirm:trader", 99)
    assert fr.get_state("trader") == fr.RETIRED
    fr.set_state("trader", fr.ACTIVE)  # restore
