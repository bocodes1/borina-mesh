"""HTTP API for the tmux/claude agent session pool."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agents.runner_v2 import run_agent_task
from agents.tmux_supervisor import get_supervisor


router = APIRouter()


# --- request bodies ---------------------------------------------------------

class SpawnBody(BaseModel):
    workdir: str
    system_prompt: str = ""


class PromptBody(BaseModel):
    prompt: str
    wait: bool = True
    idle_seconds: int = 4
    timeout_seconds: int = 60


# --- helpers ----------------------------------------------------------------

def _err_detail(e: Exception) -> str:
    """Always return a typed error string per the spec."""
    return f"{type(e).__name__}: {e!r}"


def _http_500(e: Exception) -> HTTPException:
    return HTTPException(status_code=500, detail=_err_detail(e))


def _http_404(agent_id: str) -> HTTPException:
    err = KeyError(f"agent {agent_id!r} not found")
    return HTTPException(status_code=404, detail=_err_detail(err))


# --- endpoints --------------------------------------------------------------

@router.get("")
@router.get("/")
async def list_sessions() -> dict:
    try:
        names = get_supervisor().list_sessions()
        return {"sessions": names, "count": len(names)}
    except Exception as e:
        raise _http_500(e)


@router.post("/{agent_id}")
async def spawn_session(agent_id: str, body: SpawnBody) -> dict:
    try:
        supervisor = get_supervisor()
        loop = asyncio.get_event_loop()
        name = await loop.run_in_executor(
            None,
            supervisor.spawn,
            agent_id,
            body.workdir,
            body.system_prompt,
        )
        return {
            "ok": True,
            "agent_id": agent_id,
            "session": name,
            "workdir": body.workdir,
        }
    except Exception as e:
        raise _http_500(e)


@router.delete("/{agent_id}")
async def kill_session(agent_id: str) -> dict:
    try:
        supervisor = get_supervisor()
        if not supervisor.session_exists(agent_id):
            raise _http_404(agent_id)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, supervisor.kill, agent_id)
        return {"ok": True, "agent_id": agent_id}
    except HTTPException:
        raise
    except Exception as e:
        raise _http_500(e)


@router.post("/{agent_id}/restart")
async def restart_session(agent_id: str) -> dict:
    try:
        supervisor = get_supervisor()
        if not supervisor.session_exists(agent_id):
            raise _http_404(agent_id)
        loop = asyncio.get_event_loop()
        name = await loop.run_in_executor(None, supervisor.restart, agent_id)
        return {"ok": True, "agent_id": agent_id, "session": name}
    except HTTPException:
        raise
    except Exception as e:
        raise _http_500(e)


@router.post("/{agent_id}/prompt")
async def send_prompt(agent_id: str, body: PromptBody) -> dict:
    try:
        if body.wait:
            result = await run_agent_task(
                agent_id,
                body.prompt,
                timeout_seconds=body.timeout_seconds,
                idle_seconds=body.idle_seconds,
            )
            return {
                "ok": result.ok,
                "agent_id": agent_id,
                "output": result.output,
                "error": result.error or None,
            }

        # Fire-and-forget mode: just type the prompt and return.
        supervisor = get_supervisor()
        if not supervisor.session_exists(agent_id):
            raise _http_404(agent_id)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, supervisor.send_prompt, agent_id, body.prompt
        )
        return {"ok": True, "agent_id": agent_id, "queued": True}
    except HTTPException:
        raise
    except Exception as e:
        raise _http_500(e)


@router.get("/{agent_id}/capture")
async def capture(agent_id: str, lines: int = 200) -> dict:
    try:
        supervisor = get_supervisor()
        if not supervisor.session_exists(agent_id):
            raise _http_404(agent_id)
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(
            None, supervisor.capture, agent_id, lines
        )
        return {"agent_id": agent_id, "lines": lines, "output": text}
    except HTTPException:
        raise
    except Exception as e:
        raise _http_500(e)


@router.get("/{agent_id}/stream")
async def stream(agent_id: str, request: Request, lines: int = 200):
    """SSE stream — emits a 'data' event whenever the captured pane changes."""
    async def gen():
        try:
            supervisor = get_supervisor()
        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'error': _err_detail(e)})}\n\n"
            return

        last: str | None = None
        # Fail closed if session vanishes.
        try:
            while True:
                if await request.is_disconnected():
                    return
                if not supervisor.session_exists(agent_id):
                    yield (
                        "event: error\n"
                        f"data: {json.dumps({'error': f'session for agent {agent_id!r} not found'})}\n\n"
                    )
                    return
                try:
                    cur = supervisor.capture(agent_id, lines)
                except Exception as e:
                    yield (
                        "event: error\n"
                        f"data: {json.dumps({'error': _err_detail(e)})}\n\n"
                    )
                    return
                if cur != last:
                    last = cur
                    yield f"data: {json.dumps({'output': cur})}\n\n"
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            return

    return StreamingResponse(gen(), media_type="text/event-stream")
