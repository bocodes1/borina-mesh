"""Schedule management routes."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from scheduler import scheduler_service
from agents.base import registry

router = APIRouter(prefix="/schedules", tags=["schedules"])


class ScheduleUpdate(BaseModel):
    cron: str


@router.get("")
async def list_schedules():
    """List all active schedules."""
    return scheduler_service.list_schedules()


@router.put("/{agent_id}")
async def set_schedule(agent_id: str, body: ScheduleUpdate):
    """Set or update an agent's schedule."""
    if not registry.get(agent_id):
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    try:
        scheduler_service.set_schedule(agent_id, body.cron)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"agent_id": agent_id, "cron": body.cron}


@router.delete("/{agent_id}")
async def remove_schedule(agent_id: str):
    """Remove an agent's schedule."""
    scheduler_service.remove_schedule(agent_id)
    return {"agent_id": agent_id, "removed": True}
