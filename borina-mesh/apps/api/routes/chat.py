"""Chat with agents via Server-Sent Events."""

import json
import asyncio
from fastapi import APIRouter, HTTPException
from sqlmodel import Session
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel
from agents.base import registry
from db import engine
from models import ChatMessage

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    prompt: str


@router.post("/{agent_id}")
async def chat(agent_id: str, body: ChatRequest):
    """Stream agent response via SSE."""
    agent = registry.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    # Persist user message
    with Session(engine) as session:
        session.add(ChatMessage(
            agent_id=agent_id, role="user", content=body.prompt,
        ))
        session.commit()

    async def event_generator():
        full_output = ""
        try:
            async for chunk in agent.stream(body.prompt):
                if chunk.get("type") == "text":
                    full_output += chunk.get("content", "")
                yield {
                    "event": "message",
                    "data": json.dumps(chunk),
                }
                await asyncio.sleep(0.01)
        except Exception as e:
            yield {
                "event": "error",
                "data": json.dumps({"error": str(e)}),
            }
        finally:
            if full_output:
                with Session(engine) as session:
                    session.add(ChatMessage(
                        agent_id=agent_id,
                        role="assistant",
                        content=full_output,
                    ))
                    session.commit()

    return EventSourceResponse(event_generator())
