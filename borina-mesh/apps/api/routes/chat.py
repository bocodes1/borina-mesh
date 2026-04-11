"""Chat with agents via Server-Sent Events."""

import json
import asyncio
from datetime import datetime
from fastapi import APIRouter, HTTPException
from sqlmodel import Session
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel

from agents.base import registry
from agents.qa_director import QADirector, ReviewVerdict
from db import engine
from models import Job, AgentRun, JobStatus, ChatMessage

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    prompt: str


@router.post("/{agent_id}")
async def chat(agent_id: str, body: ChatRequest, raw: bool = False):
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
        qa_verdict = None
        qa_notes = None
        full_output = ""
        tokens_used = 0

        try:
            async for chunk in agent.stream(body.prompt, job_id=job_id):
                if chunk.get("type") == "text":
                    output_parts.append(chunk.get("content", ""))
                elif chunk.get("type") == "done":
                    tokens_used = chunk.get("tokens_used", 0)
                elif chunk.get("type") == "error":
                    error_msg = chunk.get("content", "unknown error")
                yield {
                    "event": "message",
                    "data": json.dumps(chunk),
                }
                await asyncio.sleep(0.01)

            full_output = "".join(output_parts)

            # QA Director gatekeeper
            if not raw and not error_msg and full_output:
                try:
                    qa = QADirector()
                    review = await qa.review(full_output, body.prompt)
                    qa_verdict = review.verdict.value
                    qa_notes = review.notes
                    if review.verdict == ReviewVerdict.BLOCK:
                        full_output = f"[BLOCKED BY QA DIRECTOR] {review.notes}"
                    elif review.verdict == ReviewVerdict.APPROVE_WITH_NOTES:
                        full_output = f"{full_output}\n\n---\nQA notes: {review.notes}"
                except Exception as e:
                    qa_notes = f"QA review failed: {e}"

        except Exception as e:
            error_msg = str(e)
            full_output = "".join(output_parts)
            yield {
                "event": "error",
                "data": json.dumps({"error": error_msg}),
            }

        # Save BEFORE the generator ends — not in finally (which can be skipped
        # if the SSE client disconnects before reading all events).
        _save_job_result(
            job_id=job_id,
            agent_id=agent_id,
            prompt=body.prompt,
            full_output=full_output,
            error_msg=error_msg,
            tokens_used=tokens_used,
            qa_verdict=qa_verdict,
            qa_notes=qa_notes,
        )

    return EventSourceResponse(event_generator())


def _save_job_result(
    *,
    job_id: int,
    agent_id: str,
    prompt: str,
    full_output: str,
    error_msg: str | None,
    tokens_used: int,
    qa_verdict: str | None,
    qa_notes: str | None,
):
    """Persist job completion, AgentRun, ChatMessage, and artifact file."""
    # Persist assistant message
    if full_output:
        with Session(engine) as session:
            session.add(ChatMessage(
                agent_id=agent_id,
                role="assistant",
                content=full_output,
                job_id=job_id,
            ))
            session.commit()

    # Persist job status + agent run
    with Session(engine) as session:
        final_job = session.get(Job, job_id)
        if final_job:
            final_job.completed_at = datetime.utcnow()
            if error_msg:
                final_job.status = JobStatus.FAILED
                final_job.error = error_msg
            else:
                final_job.status = JobStatus.COMPLETED
                run = AgentRun(
                    job_id=job_id,
                    agent_id=agent_id,
                    output=full_output,
                    tokens_used=tokens_used,
                    cost_usd=round(tokens_used * 0.000015, 6),
                    qa_verdict=qa_verdict,
                    qa_notes=qa_notes,
                )
                session.add(run)
            session.add(final_job)
            session.commit()

    # Save artifact file
    try:
        from artifacts import save_run_output
        save_run_output(
            agent_id=agent_id,
            job_id=job_id,
            prompt=prompt,
            output=full_output if not error_msg else f"ERROR: {error_msg}\n\n{full_output}",
            status="completed" if not error_msg else "failed",
        )
    except Exception as e:
        print(f"[chat] Failed to save artifact: {e}")
