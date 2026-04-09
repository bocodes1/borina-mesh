"""Chat with agents via Server-Sent Events."""

import json
import asyncio
from datetime import datetime
from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel
from sqlmodel import Session

from agents.base import registry
from db import engine
from models import Job, AgentRun, JobStatus

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    prompt: str


@router.post("/{agent_id}")
async def chat(agent_id: str, body: ChatRequest):
    """Stream agent response via SSE."""
    agent = registry.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    with Session(engine) as session:
        job = Job(
            agent_id=agent_id,
            prompt=body.prompt,
            status=JobStatus.RUNNING,
            started_at=datetime.utcnow(),
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id = job.id

    async def event_generator():
        output_parts = []
        error_msg = None
        try:
            async for chunk in agent.stream(body.prompt, job_id=job_id):
                if chunk.get("type") == "text":
                    output_parts.append(chunk.get("content", ""))
                elif chunk.get("type") == "error":
                    error_msg = chunk.get("content", "unknown error")
                yield {
                    "event": "message",
                    "data": json.dumps(chunk),
                }
                await asyncio.sleep(0.01)
        except Exception as e:
            error_msg = str(e)
            yield {
                "event": "error",
                "data": json.dumps({"error": error_msg}),
            }
        finally:
            with Session(engine) as session:
                final_job = session.get(Job, job_id)
                if final_job:
                    final_job.completed_at = datetime.utcnow()
                    if error_msg:
                        final_job.status = JobStatus.FAILED
                        final_job.error = error_msg
                    else:
                        final_job.status = JobStatus.COMPLETED
                        full_output = "".join(output_parts)
                        run = AgentRun(
                            job_id=job_id,
                            agent_id=agent_id,
                            output=full_output,
                            tokens_used=0,
                            cost_usd=0.0,
                        )
                        session.add(run)
                    session.add(final_job)
                    session.commit()

    return EventSourceResponse(event_generator())
