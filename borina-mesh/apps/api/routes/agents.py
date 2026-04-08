"""Agent discovery routes."""

from fastapi import APIRouter, HTTPException
from agents.base import registry

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("")
async def list_agents():
    """List all registered agents."""
    return [a.to_dict() for a in registry.list()]


@router.get("/{agent_id}")
async def get_agent(agent_id: str):
    """Get a single agent by id."""
    agent = registry.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    return agent.to_dict()
