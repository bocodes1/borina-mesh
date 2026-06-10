"""Daily command-surface API (spec §5).

Mounted at `/daily` (frontend: `/api/daily/...`). Tasks CRUD lives in
`routes/tasks.py`; this exposes the rolled-up summary the /daily tab renders:
the brief's daily-relevant sections + live weather + open tasks.
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlmodel import Session, select

from db import get_session
from models import Task
from daily_brief import sections_for, today_str, load_brief
from integrations import weather

router = APIRouter(prefix="/daily", tags=["daily"])

# Sections of the daily brief that the /daily tab consumes.
DAILY_SECTIONS = ["tldr", "tasks_focus", "nudges", "weather_logistics"]


@router.get("/summary")
def daily_summary(session: Session = Depends(get_session)):
    sections = sections_for(None, DAILY_SECTIONS)
    open_tasks = session.exec(
        select(Task).where(Task.done == False).order_by(Task.sort_order, Task.due)  # noqa: E712
    ).all()
    return {
        "date": today_str(),
        "has_brief": any(v is not None for v in sections.values()),
        "brief": sections,
        "weather": weather.get_current().to_dict(),
        "open_tasks": open_tasks,
    }


@router.get("/brief")
def full_brief():
    """The full daily-brief artifact (raw markdown + all parsed sections)."""
    brief = load_brief()
    if not brief:
        return {"date": today_str(), "exists": False, "raw": None, "sections": {}}
    return {"date": brief["date"], "exists": True, "raw": brief["raw"], "sections": brief["sections"]}


@router.post("/generate", status_code=201)
async def generate_brief(use_agent: bool = Query(True)):
    """Manually trigger schedule_daily. With use_agent=false, writes the
    deterministic fallback brief (no LLM) — used for verification."""
    from schedule_daily import generate_daily_brief

    path = await generate_daily_brief(use_agent=use_agent)
    brief = load_brief()
    return {
        "written": str(path),
        "date": today_str(),
        "sections_found": sorted((brief or {}).get("sections", {}).keys()),
    }


# ── Planner (Phase 3 §3) — staged proposals, approve commits the write ───────
@router.get("/plan")
def daily_plan():
    """Today's planner proposal (tasks + proposed calendar changes + status)."""
    from planner import get_plan

    return get_plan()


@router.post("/plan/generate", status_code=201)
async def generate_plan_now(use_agent: bool = Query(True)):
    """Manually run the planner (writes daily-plan.md + proposals; never the
    calendar). With use_agent=false, uses the deterministic heuristics only."""
    from planner import generate_plan, generate_plan_with_agent

    if use_agent:
        return await generate_plan_with_agent()
    return generate_plan()


@router.post("/plan/{item_id}/approve")
def approve_plan_item(item_id: int):
    """Approve one proposed item — THIS is the user-initiated action that commits
    the calendar write / task creation."""
    from planner import approve_item

    try:
        return approve_item(item_id)
    except KeyError:
        raise HTTPException(404, "plan item not found")


@router.post("/plan/{item_id}/reject")
def reject_plan_item(item_id: int):
    from planner import reject_item

    try:
        return reject_item(item_id)
    except KeyError:
        raise HTTPException(404, "plan item not found")
