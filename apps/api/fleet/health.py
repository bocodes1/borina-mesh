"""Fleet health checks (L4) — pure functions over Job/AgentRun/AgentConfig.

Each returns a list of findings: {kind, agent|job_id, severity, detail}. Nothing
here mutates state; the sweep decides what to do with the findings.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlmodel import Session, select, func

IDLE_DAYS = 7
FAILRATE_MIN_RUNS = 5
FAILRATE_THRESHOLD = 0.5
ORPHAN_HOURS = {"telegram_dispatch": 2, "builder": 6, "goal": 12}
DEFAULT_ORPHAN_HOURS = 4


def _last_run(s: Session, *agent_ids: str):
    from models import Job
    rows = s.exec(
        select(func.max(Job.created_at)).where(Job.agent_id.in_(agent_ids))
    ).one()
    return rows


def idle_agents(engine, *, now: datetime | None = None, days: int = IDLE_DAYS) -> list[dict]:
    """Active agents whose most recent run is older than `days` → suggest park."""
    from fleet_roster import list_roster, LONG_TO_SHORT, ACTIVE
    now = now or datetime.utcnow()
    cutoff = now - timedelta(days=days)
    findings = []
    with Session(engine) as s:
        for r in list_roster():
            if r["state"] != ACTIVE:
                continue
            long_id = r["id"]
            short = LONG_TO_SHORT.get(long_id, long_id)
            last = _last_run(s, long_id, short)
            if last is None or last < cutoff:
                findings.append({
                    "kind": "idle", "agent": long_id, "severity": "warn",
                    "detail": f"no run in {days}d" if last else "never run",
                })
    return findings


def failing_agents(engine, *, now: datetime | None = None) -> list[dict]:
    """Agents with ≥5 runs in 7d and a ≥50% failure rate."""
    from models import Job, JobStatus
    now = now or datetime.utcnow()
    since = now - timedelta(days=7)
    findings = []
    with Session(engine) as s:
        rows = s.exec(select(Job).where(Job.created_at >= since)).all()
    by_agent: dict[str, list] = {}
    for j in rows:
        by_agent.setdefault(j.agent_id, []).append(j)
    for agent, jobs in by_agent.items():
        total = len(jobs)
        failed = sum(1 for j in jobs if j.status == JobStatus.FAILED)
        if total >= FAILRATE_MIN_RUNS and failed / total >= FAILRATE_THRESHOLD:
            findings.append({
                "kind": "failing", "agent": agent, "severity": "alert",
                "detail": f"{failed}/{total} failed in 7d",
            })
    return findings


def orphaned_jobs(engine, *, now: datetime | None = None) -> list[dict]:
    """Jobs stuck RUNNING far longer than their kind should take."""
    from models import Job, JobStatus
    now = now or datetime.utcnow()
    findings = []
    with Session(engine) as s:
        running = s.exec(select(Job).where(Job.status == JobStatus.RUNNING)).all()
    for j in running:
        limit = ORPHAN_HOURS.get(j.kind, DEFAULT_ORPHAN_HOURS)
        started = j.started_at or j.created_at
        if started and (now - started) > timedelta(hours=limit):
            findings.append({
                "kind": "orphan", "job_id": j.id, "agent": j.agent_id, "severity": "alert",
                "detail": f"running >{limit}h ({j.kind})",
            })
    return findings


def check_fleet(engine, *, now: datetime | None = None) -> list[dict]:
    """All findings, most severe first."""
    findings = idle_agents(engine, now=now) + failing_agents(engine, now=now) + orphaned_jobs(engine, now=now)
    order = {"alert": 0, "warn": 1, "info": 2}
    return sorted(findings, key=lambda f: order.get(f["severity"], 9))
