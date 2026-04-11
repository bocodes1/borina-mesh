"""Agent discovery routes."""

from fastapi import APIRouter, HTTPException
from agents.base import registry
from agents.models import AGENT_MODELS, resolve_model
from agent_status import get_agent_status
from db import engine

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("")
async def list_agents():
    """List all registered agents with live status."""
    agents = []
    for a in registry.list():
        d = a.to_dict()
        status_info = get_agent_status(a.id, engine)
        d["status"] = status_info["status"]
        d["current_task"] = status_info["current_task"]
        d["last_run_at"] = status_info["last_run_at"]
        agents.append(d)
    return agents


@router.get("/models")
def get_agent_models() -> dict[str, str]:
    """Get live model mapping for each agent."""
    return {aid: resolve_model(aid) for aid in AGENT_MODELS}


@router.get("/{agent_id}")
async def get_agent(agent_id: str):
    """Get a single agent by id."""
    agent = registry.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    d = agent.to_dict()
    status_info = get_agent_status(agent_id, engine)
    d.update(status_info)
    return d
