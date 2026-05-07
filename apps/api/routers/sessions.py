"""FastAPI router for tmux-supervised `claude` sessions.

Endpoints (mounted at /api/sessions in main.py):
  GET    /                       — list all known sessions
  POST   /{agent_id}              — spawn a session
  DELETE /{agent_id}              — kill a session
  POST   /{agent_id}/restart      — kill + respawn
  POST   /{agent_id}/prompt       — send a prompt; if wait=True, return the response
  GET    /{agent_id}/capture      — current pane text
  GET    /{agent_id}/stream       — SSE stream, emits only when text changes

All errors surface as ``{type(e).__name__}: {e!r}`` so the cause is never
mystery-empty in the dashboard logs.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from agents.runner_v2 import run_agent_task
from agents.tmux_supervisor import get_supervisor

router = APIRouter()


# ── request models ────────────────────────────────────────────────────────

class SpawnReq(BaseModel):
    workdir: str
    system_prompt: str = ""


class PromptReq(BaseModel):
    prompt: str
    wait: bool = True
    idle_seconds: int = Field(default=4, ge=1, le=60)
    timeout_seconds: int = Field(default=60, ge=1, le=3600)


# ── helpers ───────────────────────────────────────────────────────────────

def _typed(e: Exception, status: int = 500) -> HTTPException:
    return HTTPException(
        status_code=status,
        detail=f"{type(e).__name__}: {e!r}",
    )


def _require_session(agent_id: str) -> None:
    sup = get_supervisor()
    if not sup.session_exists(agent_id):
        raise HTTPException(
            status_code=404,
            detail=f"KeyError: agent_id '{agent_id}' is not known — no tmux session found",
        )


# ── endpoints ─────────────────────────────────────────────────────────────

@router.get("")
@router.get("/")
def list_sessions():
    try:
        return get_supervisor().list_sessions()
    except Exception as e:
        raise _typed(e)


@router.post("/{agent_id}")
def spawn_session(agent_id: str, req: SpawnReq):
    try:
        info = get_supervisor().spawn(agent_id, req.workdir, req.system_prompt)
        return {
            "ok": True,
            "agent_id": info.agent_id,
            "session_name": info.session_name,
            "workdir": info.workdir,
            "spawned_at": info.spawned_at,
        }
    except Exception as e:
        raise _typed(e)


@router.delete("/{agent_id}")
def kill_session(agent_id: str):
    try:
        sup = get_supervisor()
        if not sup.session_exists(agent_id):
            raise HTTPException(
                status_code=404,
                detail=f"KeyError: agent_id '{agent_id}' is not known",
            )
        sup.kill(agent_id)
        return {"ok": True, "agent_id": agent_id}
    except HTTPException:
        raise
    except Exception as e:
        raise _typed(e)


@router.post("/{agent_id}/restart")
def restart_session(agent_id: str):
    sup = get_supervisor()
    known = {s["agent_id"] for s in sup.list_sessions()}
    if not sup.session_exists(agent_id) and agent_id not in known:
        raise HTTPException(
            status_code=404,
            detail=f"KeyError: agent_id '{agent_id}' is not known to supervisor",
        )
    try:
        info = sup.restart(agent_id)
        return {
            "ok": True,
            "agent_id": info.agent_id,
            "session_name": info.session_name,
            "workdir": info.workdir,
        }
    except KeyError as e:
        raise HTTPException(
            status_code=404,
            detail=f"KeyError: {e!r}",
        )
    except Exception as e:
        raise _typed(e)


@router.post("/{agent_id}/prompt")
async def prompt_session(agent_id: str, req: PromptReq):
    sup = get_supervisor()
    # run_agent_task lazy-spawns if needed, so don't 404 here when missing.
    try:
        if req.wait:
            result = await run_agent_task(
                agent_id, req.prompt,
                timeout_seconds=req.timeout_seconds,
                idle_seconds=req.idle_seconds,
            )
            return {
                "ok": result.ok,
                "agent_id": agent_id,
                "output": result.output,
                "error": result.error,
                "duration_seconds": result.duration_seconds,
                "timed_out": result.timed_out,
            }
        else:
            if not sup.session_exists(agent_id):
                raise HTTPException(
                    status_code=404,
                    detail=f"KeyError: agent_id '{agent_id}' has no session — spawn first or use wait=True",
                )
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, sup.send_prompt, agent_id, req.prompt)
            return {"ok": True, "agent_id": agent_id, "queued": True}
    except HTTPException:
        raise
    except Exception as e:
        raise _typed(e)


@router.get("/{agent_id}/capture")
def capture_session(agent_id: str, lines: int = 200):
    _require_session(agent_id)
    try:
        text = get_supervisor().capture(agent_id, lines=lines)
        return {"agent_id": agent_id, "lines": lines, "text": text}
    except Exception as e:
        raise _typed(e)


@router.get("/{agent_id}/stream")
async def stream_session(agent_id: str):
    """SSE stream of pane content; emits only when the captured text changes."""

    async def event_gen():
        sup = get_supervisor()
        last = ""
        while True:
            if not sup.session_exists(agent_id):
                yield {
                    "event": "error",
                    "data": f"KeyError: agent_id '{agent_id}' has no tmux session",
                }
                return
            try:
                current = sup.capture(agent_id, lines=200)
            except Exception as e:
                yield {"event": "error", "data": f"{type(e).__name__}: {e!r}"}
                return
            if current != last:
                last = current
                yield {"event": "update", "data": current}
            await asyncio.sleep(0.5)

    return EventSourceResponse(event_gen())
