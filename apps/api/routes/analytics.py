"""Analytics routes - token usage, cost, run counts."""

from datetime import datetime, timedelta
from collections import defaultdict
from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from db import get_session
from models import AgentRun

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary")
async def summary(session: Session = Depends(get_session)):
    """Aggregate totals + per-agent breakdown."""
    runs = session.exec(select(AgentRun)).all()
    runs_by_agent: dict[str, dict] = defaultdict(lambda: {"runs": 0, "tokens": 0, "cost_usd": 0.0})
    for r in runs:
        runs_by_agent[r.agent_id]["runs"] += 1
        runs_by_agent[r.agent_id]["tokens"] += r.tokens_used
        runs_by_agent[r.agent_id]["cost_usd"] += r.cost_usd

    return {
        "total_runs": len(runs),
        "total_tokens": sum(r.tokens_used for r in runs),
        "total_cost_usd": round(sum(r.cost_usd for r in runs), 4),
        "runs_by_agent": dict(runs_by_agent),
    }


@router.get("/timeseries")
async def timeseries(days: int = 7, session: Session = Depends(get_session)):
    """Daily run/token/cost counts for the last N days."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    runs = session.exec(select(AgentRun).where(AgentRun.created_at >= cutoff)).all()

    buckets: dict[str, dict] = defaultdict(lambda: {"runs": 0, "tokens": 0, "cost_usd": 0.0})
    for r in runs:
        key = r.created_at.date().isoformat()
        buckets[key]["runs"] += 1
        buckets[key]["tokens"] += r.tokens_used
        buckets[key]["cost_usd"] += round(r.cost_usd, 4)

    result = []
    for i in range(days):
        d = (datetime.utcnow().date() - timedelta(days=days - 1 - i)).isoformat()
        row = buckets.get(d, {"runs": 0, "tokens": 0, "cost_usd": 0.0})
        result.append({"date": d, **row})
    return result
