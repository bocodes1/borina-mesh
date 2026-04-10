"""Agent memory API routes."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from memory import read_memory, append_memory

router = APIRouter(prefix="/memory", tags=["memory"])


class AppendRequest(BaseModel):
    entry: str


@router.get("/agent/{agent_id}")
async def get_agent_memory(agent_id: str):
    """Read an agent's memory file."""
    content = read_memory(agent_id)
    return {"agent_id": agent_id, "content": content}


@router.post("/agent/{agent_id}/append")
async def append_agent_memory(agent_id: str, body: AppendRequest):
    """Append an entry to an agent's memory file."""
    if not body.entry.strip():
        raise HTTPException(status_code=400, detail="Entry cannot be empty")
    append_memory(agent_id, body.entry)
    return {"agent_id": agent_id, "appended": True}
