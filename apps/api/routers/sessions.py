"""FastAPI router exposing the tmux supervisor + runner.

All endpoints are mounted at `/api/sessions` from `main.py`. Errors are
serialized as `{type(e).__name__}: {repr(e)}` in the `detail` field so callers
can tell `KeyError("trader")` from `RuntimeError("...PATH=...")` without
parsing log files.

Endpoints:
    GET    /                      list sessions
    POST   /{agent_id}             spawn (workdir + system_prompt in body)
    DELETE /{agent_id}             kill
    POST   /{agent_id}/restart     restart
    POST   /{agent_id}/prompt      send prompt; if wait=True, await response
    GET    /{agent_id}/capture     last N lines of the pane
    GET    /{agent_id}/stream      SSE — emits when pane changes
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from agents.runner_v2 import AGENT_REGISTRY, run_agent_task, _workdir_for
from agents.tmux_supervisor import get_supervisor

router = APIRouter()


def _typed_detail(e: Exception) -> str:
    """All errors come back as `Type: repr(e)` so the client can match precisely."""
    return f"{type(e).__name__}: {e!r}"


# ───────────────────────── request models ──────────────────────────
class SpawnBody(BaseModel):
    workdir: Optional[str] = None
    system_prompt: Optional[str] = None


class PromptBody(BaseModel):
    prompt: str
    wait: bool = True
    idle_seconds: float = 4.0
    timeout_seconds: float = 600.0


# ───────────────────────── endpoints ───────────────────────────────
@router.get("")
@router.get("/")
def list_sessions():
    """Return every supervisor-tracked tmux session."""
    try:
        sup = get_supervisor()
        return {"sessions": sup.list_sessions()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=_typed_detail(e)) from e


@router.post("/{agent_id}")
def spawn_session(agent_id: str, body: SpawnBody):
    """Spawn (or re-adopt) a tmux session running claude for this agent."""
    try:
        spec = AGENT_REGISTRY.get(agent_id)
        workdir = body.workdir or (_workdir_for(agent_id))
        system_prompt = body.system_prompt
        if system_prompt is None:
            system_prompt = spec.system_prompt if spec else ""

        sup = get_supervisor()
        info = sup.spawn(agent_id, workdir, system_prompt)
        return {
            "ok": True,
            "agent_id": info.agent_id,
            "session_name": info.session_name,
            "workdir": info.workdir,
            "started_at": info.started_at,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=_typed_detail(e)) from e


@router.delete("/{agent_id}")
def kill_session(agent_id: str):
    try:
        sup = get_supervisor()
        if not sup.session_exists(agent_id):
            raise HTTPException(
                status_code=404,
                detail=f"KeyError: tmux session for agent {agent_id!r} not found",
            )
        sup.kill(agent_id)
        return {"ok": True, "agent_id": agent_id, "killed": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=_typed_detail(e)) from e


@router.post("/{agent_id}/restart")
def restart_session(agent_id: str):
    try:
        sup = get_supervisor()
        if not sup.session_exists(agent_id):
            raise HTTPException(
                status_code=404,
                detail=(
                    f"KeyError: agent {agent_id!r} is not known to the supervisor "
                    "(spawn it first)"
                ),
            )
        info = sup.restart(agent_id)
        return {
            "ok": True,
            "agent_id": info.agent_id,
            "session_name": info.session_name,
            "restarted_at": info.started_at,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=_typed_detail(e)) from e


@router.post("/{agent_id}/prompt")
async def send_prompt(agent_id: str, body: PromptBody):
    """Inject a prompt; optionally block until the pane goes idle and return
    the captured response."""
    try:
        if body.wait:
            result = await run_agent_task(
                agent_id,
                body.prompt,
                timeout_seconds=int(body.timeout_seconds),
                idle_seconds=int(body.idle_seconds),
            )
            return {
                "ok": result.ok,
                "agent_id": result.agent_id,
                "output": result.output,
                "error": result.error,
                "timed_out": result.timed_out,
                "started_at": result.started_at,
                "completed_at": result.completed_at,
                "metadata": result.metadata,
            }

        # Fire-and-forget mode: lazy-spawn then send_prompt only.
        sup = get_supervisor()
        if not sup.session_exists(agent_id):
            spec = AGENT_REGISTRY.get(agent_id)
            sys_prompt = spec.system_prompt if spec else ""
            sup.spawn(agent_id, _workdir_for(agent_id), sys_prompt)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, sup.send_prompt, agent_id, body.prompt)
        return {"ok": True, "agent_id": agent_id, "queued": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=_typed_detail(e)) from e


@router.get("/{agent_id}/capture")
def capture_pane(agent_id: str, lines: int = 200):
    try:
        sup = get_supervisor()
        if not sup.session_exists(agent_id):
            raise HTTPException(
                status_code=404,
                detail=f"KeyError: tmux session for agent {agent_id!r} not found",
            )
        text = sup.capture(agent_id, lines=lines)
        return {"ok": True, "agent_id": agent_id, "lines": lines, "text": text}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=_typed_detail(e)) from e


@router.get("/{agent_id}/stream")
async def stream_pane(agent_id: str, lines: int = 200, poll_ms: int = 500):
    """SSE stream of pane content; only emits on change."""
    sup = get_supervisor()
    if not sup.session_exists(agent_id):
        raise HTTPException(
            status_code=404,
            detail=f"KeyError: tmux session for agent {agent_id!r} not found",
        )

    async def event_gen():
        last = ""
        loop = asyncio.get_running_loop()
        delay = max(0.1, poll_ms / 1000.0)
        while True:
            try:
                current = await loop.run_in_executor(None, sup.capture, agent_id, lines)
            except Exception as e:
                yield {"event": "error", "data": _typed_detail(e)}
                return
            if current != last:
                last = current
                yield {"event": "update", "data": current}
            await asyncio.sleep(delay)

    return EventSourceResponse(event_gen())
