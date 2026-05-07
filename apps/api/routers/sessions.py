"""FastAPI router for managing tmux-hosted claude sessions.

Mounted at `/api/sessions` from `main.py`. All errors propagate as HTTP 5xx
with `{type(e).__name__}: {e!r}` in `detail` so failures are debuggable.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agents.runner_v2 import AGENT_REGISTRY, run_agent_task
from agents.tmux_supervisor import get_supervisor

router = APIRouter()


class SpawnRequest(BaseModel):
    workdir: str = Field(..., description="Absolute working directory for the claude session")
    system_prompt: str = Field("", description="System prompt appended to the default")


class PromptRequest(BaseModel):
    prompt: str
    wait: bool = True
    idle_seconds: float = 4.0
    timeout_seconds: float = 60.0
    fresh_context: bool = False


def _typed_error(e: Exception) -> str:
    return f"{type(e).__name__}: {e!r}"


@router.get("")
@router.get("/")
async def list_sessions():
    """List every tracked + tmux-visible session belonging to this pane."""
    try:
        return {"sessions": get_supervisor().list_sessions()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=_typed_error(e))


@router.post("/{agent_id}")
async def spawn_session(agent_id: str, body: SpawnRequest):
    """Spawn (or re-adopt) the agent's claude tmux session."""
    try:
        info = get_supervisor().spawn(agent_id, body.workdir, body.system_prompt)
        return {
            "agent_id": info.agent_id,
            "session_name": info.session_name,
            "workdir": info.workdir,
            "created_at": info.created_at,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=_typed_error(e))


@router.delete("/{agent_id}")
async def kill_session(agent_id: str):
    """Tear down the agent's tmux session."""
    sup = get_supervisor()
    try:
        if not sup.session_exists(agent_id):
            raise HTTPException(
                status_code=404,
                detail=f"KeyError: agent {agent_id!r} session not found",
            )
        killed = sup.kill(agent_id)
        return {"agent_id": agent_id, "killed": killed}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=_typed_error(e))


@router.post("/{agent_id}/restart")
async def restart_session(agent_id: str):
    """Kill + respawn using the previously registered workdir/system_prompt."""
    sup = get_supervisor()
    try:
        # Lazy auto-spawn for known runner_v2 agents that haven't been registered yet.
        if agent_id not in sup._sessions and agent_id in AGENT_REGISTRY:
            from agents.runner_v2 import _default_workdir, _resolve_system_prompt
            sup.spawn(agent_id, _default_workdir(agent_id), _resolve_system_prompt(agent_id))
        if agent_id not in sup._sessions:
            raise HTTPException(
                status_code=404,
                detail=f"KeyError: agent {agent_id!r} not known — spawn() it first",
            )
        info = sup.restart(agent_id)
        return {
            "agent_id": info.agent_id,
            "session_name": info.session_name,
            "workdir": info.workdir,
            "restarted_at": time.time(),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=_typed_error(e))


@router.post("/{agent_id}/prompt")
async def post_prompt(agent_id: str, body: PromptRequest):
    """Send a prompt to the agent. If wait=True, block until idle and return the response."""
    try:
        if body.wait:
            result = await run_agent_task(
                agent_id,
                body.prompt,
                timeout_seconds=body.timeout_seconds,
                idle_seconds=body.idle_seconds,
                fresh_context=body.fresh_context,
            )
            return result.to_dict()
        # fire-and-forget: ensure session exists, then paste + return
        sup = get_supervisor()
        if not sup.session_exists(agent_id):
            from agents.runner_v2 import _default_workdir, _resolve_system_prompt
            if agent_id in AGENT_REGISTRY:
                sup.spawn(agent_id, _default_workdir(agent_id), _resolve_system_prompt(agent_id))
            else:
                raise HTTPException(
                    status_code=404,
                    detail=f"KeyError: agent {agent_id!r} session not found and not in AGENT_REGISTRY",
                )
        await asyncio.to_thread(sup.send_prompt, agent_id, body.prompt)
        return {"agent_id": agent_id, "status": "submitted", "wait": False}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=_typed_error(e))


@router.get("/{agent_id}/capture")
async def capture_pane(agent_id: str, lines: int = 200):
    """Return the last `lines` of the agent's pane (ANSI-stripped)."""
    try:
        text = await asyncio.to_thread(get_supervisor().capture, agent_id, lines)
        return {"agent_id": agent_id, "lines": lines, "text": text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=_typed_error(e))


@router.get("/{agent_id}/stream")
async def stream_pane(agent_id: str, lines: int = 400, poll_ms: int = 500):
    """Server-Sent Events stream — emits the pane's tail every time it changes."""
    poll_seconds = max(poll_ms / 1000.0, 0.05)
    sup = get_supervisor()

    async def event_gen():
        if not sup.session_exists(agent_id):
            yield f"event: error\ndata: {json.dumps({'error': f'session {agent_id} not found'})}\n\n"
            return

        last_text: Optional[str] = None
        try:
            while True:
                try:
                    cur = await asyncio.to_thread(sup.capture, agent_id, lines)
                except RuntimeError as e:
                    yield f"event: error\ndata: {json.dumps({'error': _typed_error(e)})}\n\n"
                    return
                if cur != last_text:
                    last_text = cur
                    yield f"event: capture\ndata: {json.dumps({'agent_id': agent_id, 'text': cur})}\n\n"
                await asyncio.sleep(poll_seconds)
        except asyncio.CancelledError:
            return

    return StreamingResponse(event_gen(), media_type="text/event-stream")
