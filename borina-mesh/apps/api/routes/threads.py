"""Chat thread routes — conversation history per agent."""

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from db import get_session
from models import ChatMessage

router = APIRouter(prefix="/threads", tags=["threads"])


@router.get("/{agent_id}")
async def get_thread(
    agent_id: str,
    limit: int = 100,
    session: Session = Depends(get_session),
):
    """Get chat history for an agent, oldest first."""
    messages = session.exec(
        select(ChatMessage)
        .where(ChatMessage.agent_id == agent_id)
        .order_by(ChatMessage.created_at)
        .limit(limit)
    ).all()
    return list(messages)


@router.delete("/{agent_id}")
async def clear_thread(
    agent_id: str,
    session: Session = Depends(get_session),
):
    """Clear chat history for an agent."""
    messages = session.exec(
        select(ChatMessage).where(ChatMessage.agent_id == agent_id)
    ).all()
    for msg in messages:
        session.delete(msg)
    session.commit()
    return {"agent_id": agent_id, "deleted": len(messages)}
