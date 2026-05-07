"""HTTP endpoints for the tmux-supervised claude REPL pool.

All errors surface as ``{type(e).__name__}: {e!r}`` in ``detail`` so misconfigured
environments are diagnosable from the response body alone — never empty errors.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agents.runner_v2 import AgentRunResult, run_agent_task
from agents.tmux_supervisor import get_supervisor


router = APIRouter()


class SpawnRequest(BaseModel):
    workdir: str
    system_prompt: str


class PromptRequest(BaseModel):
    prompt: str
    wait: bool = True
    idle_seconds: float = 4.0
    timeout_seconds: float = 60.0


def _err_detail(e: Exception) -> str:
    return f"{type(e).__name__}: {e!r}"


@router.get("")
def list_sessions_no_slash() -> dict:
    return list_sessions()


@router.get("/")
def list_sessions() -> dict:
    try:
        return {"sessions": get_supervisor().list_sessions()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=_err_detail(e))


@router.post("/{agent_id}")
def spawn_session(agent_id: str, body: SpawnRequest) -> dict:
    try:
        info = get_supervisor().spawn(agent_id, body.workdir, body.system_prompt)
        return {
            "agent_id": info.agent_id,
            "session_name": info.session_name,
            "workdir": info.workdir,
            "created_at": info.created_at,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=_err_detail(e))


@router.delete("/{agent_id}")
def kill_session(agent_id: str) -> dict:
    try:
        killed = get_supervisor().kill(agent_id)
        return {"agent_id": agent_id, "killed": killed}
    except Exception as e:
        raise HTTPException(status_code=500, detail=_err_detail(e))


@router.post("/{agent_id}/restart")
def restart_session(agent_id: str) -> dict:
    try:
        info = get_supervisor().restart(agent_id)
        return {
            "agent_id": info.agent_id,
            "session_name": info.session_name,
            "workdir": info.workdir,
            "restarted_at": time.time(),
        }
    except RuntimeError as e:
        msg = str(e)
        if "not known" in msg:
            raise HTTPException(status_code=404, detail=_err_detail(e))
        raise HTTPException(status_code=500, detail=_err_detail(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=_err_detail(e))


@router.post("/{agent_id}/prompt")
async def send_prompt(agent_id: str, body: PromptRequest) -> dict:
    try:
        if not body.wait:
            get_supervisor().send_prompt(agent_id, body.prompt)
            return {"agent_id": agent_id, "sent": True, "waited": False}

        result: AgentRunResult = await run_agent_task(
            agent_id,
            body.prompt,
            timeout_seconds=body.timeout_seconds,
            idle_seconds=body.idle_seconds,
        )
        return {
            "agent_id": agent_id,
            "ok": result.ok,
            "output": result.output,
            "error": result.error,
            "duration_seconds": result.duration_seconds,
            "timed_out": result.timed_out,
            "session_name": result.session_name,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=_err_detail(e))


@router.get("/{agent_id}/capture")
def capture_session(agent_id: str, lines: int = 200) -> dict:
    try:
        text = get_supervisor().capture(agent_id, lines=lines)
        return {"agent_id": agent_id, "lines": lines, "text": text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=_err_detail(e))


@router.get("/{agent_id}/stream")
async def stream_session(agent_id: str, lines: int = 200, poll_ms: int = 500):
    """SSE stream — polls ``capture()`` every ``poll_ms`` and emits only when text changes."""
    try:
        sup = get_supervisor()
        # Validate up front so the response status reflects the error.
        if not sup.session_exists(agent_id):
            raise RuntimeError(
                f"session for agent {agent_id!r} does not exist; spawn first"
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=_err_detail(e))

    poll_seconds = max(0.05, poll_ms / 1000.0)

    async def _events():
        last = ""
        try:
            while True:
                try:
                    text = get_supervisor().capture(agent_id, lines=lines)
                except RuntimeError as e:
                    yield f"event: error\ndata: {json.dumps({'error': _err_detail(e)})}\n\n"
                    return
                if text != last:
                    last = text
                    yield f"event: capture\ndata: {json.dumps({'text': text})}\n\n"
                else:
                    # Keep-alive comment; clients ignore lines starting with ':'.
                    yield ": keepalive\n\n"
                await asyncio.sleep(poll_seconds)
        except asyncio.CancelledError:
            return

    return StreamingResponse(_events(), media_type="text/event-stream")
