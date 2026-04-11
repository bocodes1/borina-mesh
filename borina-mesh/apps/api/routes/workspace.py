"""Inter-agent workspace (blackboard) routes."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from db import get_session
from models import AgentWorkspace

router = APIRouter(prefix="/workspace", tags=["workspace"])


class WorkspaceWriteRequest(BaseModel):
    workspace_id: str
    agent_id: str
    key: str
    value: str


@router.get("/{workspace_id}")
async def list_workspace_entries(
    workspace_id: str,
    session: Session = Depends(get_session),
):
    """List all entries in a workspace."""
    entries = session.exec(
        select(AgentWorkspace)
        .where(AgentWorkspace.workspace_id == workspace_id)
        .order_by(AgentWorkspace.created_at)
    ).all()
    return list(entries)


@router.post("")
async def write_workspace_entry(
    body: WorkspaceWriteRequest,
    session: Session = Depends(get_session),
):
    """Write an entry to a workspace."""
    entry = AgentWorkspace(
        workspace_id=body.workspace_id,
        agent_id=body.agent_id,
        key=body.key,
        value=body.value,
    )
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


@router.delete("/{workspace_id}")
async def clear_workspace(
    workspace_id: str,
    session: Session = Depends(get_session),
):
    """Clear all entries in a workspace."""
    entries = session.exec(
        select(AgentWorkspace).where(AgentWorkspace.workspace_id == workspace_id)
    ).all()
    for entry in entries:
        session.delete(entry)
    session.commit()
    return {"workspace_id": workspace_id, "deleted": len(entries)}
