"""FastAPI router for managing the tmux-backed claude session pool."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agents.tmux_supervisor import get_supervisor
from agents.runner_v2 import run_agent_task, AgentRunResult


router = APIRouter()


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------
class SpawnBody(BaseModel):
    workdir: str = Field(..., description="Absolute path to the agent's working directory")
    system_prompt: str = Field("", description="System prompt appended to claude at launch")


class PromptBody(BaseModel):
    prompt: str = Field(..., description="User prompt to send to the agent's REPL")
    wait: bool = Field(True, description="Block on wait_for_idle and return the response")
    idle_seconds: float = Field(4.0, ge=0.1, description="Seconds of pane stillness counted as idle")
    timeout_seconds: float = Field(60.0, ge=1.0, description="Hard ceiling for wait_for_idle")


def _err(e: Exception) -> str:
    """Typed, repr-rich error string used in every HTTPException detail."""
    return f"{type(e).__name__}: {e!r}"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("")
@router.get("/")
async def list_sessions() -> dict:
    """List every borina-p{pane}-* tmux session this supervisor knows about."""
    sup = get_supervisor()
    try:
        sessions = await asyncio.to_thread(sup.list_sessions)
    except Exception as e:
        raise HTTPException(status_code=500, detail=_err(e))
    return {
        "pane_number": sup.pane_number,
        "claude_path": _safe_claude_path(sup),
        "count": len(sessions),
        "sessions": sessions,
    }


def _safe_claude_path(sup) -> Optional[str]:
    try:
        return sup.claude_path
    except Exception:
        return None


@router.post("/{agent_id}")
async def spawn_session(agent_id: str, body: SpawnBody) -> dict:
    """Create or re-adopt the agent's tmux session."""
    sup = get_supervisor()
    try:
        result = await asyncio.to_thread(
            sup.spawn, agent_id, body.workdir, body.system_prompt
        )
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=_err(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=_err(e))
    return result


@router.delete("/{agent_id}")
async def kill_session(agent_id: str) -> dict:
    sup = get_supervisor()
    try:
        killed = await asyncio.to_thread(sup.kill, agent_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=_err(e))
    return {"agent_id": agent_id, "killed": killed}


@router.post("/{agent_id}/restart")
async def restart_session(agent_id: str) -> dict:
    sup = get_supervisor()
    try:
        result = await asyncio.to_thread(sup.restart, agent_id)
    except RuntimeError as e:
        # 404 when supervisor reports the agent is unknown / has no metadata,
        # so callers can distinguish "bad id" from "tmux failed".
        msg = str(e)
        if "not known" in msg or "no metadata" in msg or "does not exist" in msg:
            raise HTTPException(status_code=404, detail=_err(e))
        raise HTTPException(status_code=400, detail=_err(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=_err(e))
    return result


@router.post("/{agent_id}/prompt")
async def send_session_prompt(agent_id: str, body: PromptBody) -> dict:
    """Send a prompt to the agent. If wait=True, block on wait_for_idle.

    On wait=True we return the AgentRunResult shape so callers get typed
    output, timed_out, and error fields.
    """
    sup = get_supervisor()
    try:
        if body.wait:
            # Use the high-level runner so we get partial-on-timeout semantics
            # and consistent error formatting. It will lazy-spawn if needed.
            result: AgentRunResult = await run_agent_task(
                agent_id,
                body.prompt,
                timeout_seconds=int(body.timeout_seconds),
                idle_seconds=int(body.idle_seconds),
            )
            payload = result.to_dict()
            # Surface the verbatim pane tail so callers can fall back to it
            # if the heuristic-extracted output is empty.
            try:
                payload["pane_tail"] = await asyncio.to_thread(sup.capture, agent_id, 200)
            except Exception:
                payload["pane_tail"] = ""
            return payload
        # Fire-and-forget mode.
        if not sup.session_exists(agent_id):
            raise RuntimeError(
                f"Session {sup.session_name(agent_id)!r} does not exist; POST /sessions/{agent_id} first"
            )
        await asyncio.to_thread(sup.send_prompt, agent_id, body.prompt)
        return {"agent_id": agent_id, "sent": True, "waited": False}
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=_err(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=_err(e))


@router.get("/{agent_id}/capture")
async def capture_session(agent_id: str, lines: int = Query(200, ge=1, le=5000)) -> dict:
    sup = get_supervisor()
    try:
        text = await asyncio.to_thread(sup.capture, agent_id, lines)
    except RuntimeError as e:
        raise HTTPException(status_code=404, detail=_err(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=_err(e))
    return {"agent_id": agent_id, "lines": lines, "text": text}


@router.get("/{agent_id}/stream")
async def stream_session(agent_id: str, lines: int = Query(200, ge=1, le=2000)):
    """Server-Sent Events: emit a frame each time the pane content changes."""
    sup = get_supervisor()

    async def gen():
        try:
            if not sup.session_exists(agent_id):
                yield "event: error\ndata: " + json.dumps(
                    {"detail": f"Session {sup.session_name(agent_id)!r} does not exist"}
                ) + "\n\n"
                return
            last_text = ""
            # Heartbeat every ~10s so proxies don't kill the connection.
            last_heartbeat = 0.0
            tick = 0
            while True:
                try:
                    text = await asyncio.to_thread(sup.capture, agent_id, lines)
                except Exception as e:
                    yield "event: error\ndata: " + json.dumps({"detail": _err(e)}) + "\n\n"
                    return
                if text != last_text:
                    yield "data: " + json.dumps({"text": text}) + "\n\n"
                    last_text = text
                tick += 1
                if tick % 20 == 0:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            return

    return StreamingResponse(gen(), media_type="text/event-stream")
