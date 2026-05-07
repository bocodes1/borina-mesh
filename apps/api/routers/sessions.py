"""HTTP API for the tmux-hosted agent session pool.

Mounted at /api/sessions by main.py. All errors return a typed
`{type(e).__name__}: {e!r}` string in the FastAPI `detail` field so
clients always have something useful to log — never an empty 500.
"""

from __future__ import annotations

import asyncio
import json
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agents.tmux_supervisor import get_supervisor
from agents.runner_v2 import run_agent_task


router = APIRouter()


def _typed(e: Exception) -> str:
    return f"{type(e).__name__}: {e!r}"


# ── request bodies ──────────────────────────────────────────────────────


class SpawnBody(BaseModel):
    workdir: str
    system_prompt: str = ""


class PromptBody(BaseModel):
    prompt: str
    wait: bool = True
    idle_seconds: float = Field(default=4.0, ge=0.5, le=120.0)
    timeout_seconds: float = Field(default=120.0, ge=1.0, le=3600.0)


# ── inventory ───────────────────────────────────────────────────────────


@router.get("")
@router.get("/")
async def list_sessions():
    try:
        sup = get_supervisor()
        return {"sessions": sup.list_sessions()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=_typed(e))


# ── spawn / kill / restart ──────────────────────────────────────────────


@router.post("/{agent_id}")
async def spawn(agent_id: str, body: SpawnBody):
    try:
        sup = get_supervisor()
        loop = asyncio.get_event_loop()
        rec = await loop.run_in_executor(
            None, sup.spawn, agent_id, body.workdir, body.system_prompt,
        )
        return {
            "ok": True,
            "agent_id": rec.agent_id,
            "session": rec.session,
            "workdir": rec.workdir,
            "started_at": rec.started_at,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=_typed(e))


@router.delete("/{agent_id}")
async def kill(agent_id: str):
    try:
        sup = get_supervisor()
        if not sup.session_exists(agent_id):
            raise HTTPException(
                status_code=404,
                detail=f"KeyError: agent '{agent_id}' has no live tmux session",
            )
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, sup.kill, agent_id)
        return {"ok": True, "agent_id": agent_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=_typed(e))


@router.post("/{agent_id}/restart")
async def restart(agent_id: str):
    try:
        sup = get_supervisor()
        loop = asyncio.get_event_loop()
        rec = await loop.run_in_executor(None, sup.restart, agent_id)
        return {
            "ok": True,
            "agent_id": agent_id,
            "session": rec.session,
            "started_at": rec.started_at,
        }
    except KeyError as e:
        # Bad agent_id — return 404 with a typed error string.
        raise HTTPException(status_code=404, detail=_typed(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=_typed(e))


# ── prompt ──────────────────────────────────────────────────────────────


@router.post("/{agent_id}/prompt")
async def prompt(agent_id: str, body: PromptBody):
    try:
        sup = get_supervisor()
        if not sup.session_exists(agent_id):
            raise HTTPException(
                status_code=404,
                detail=f"KeyError: tmux session for '{agent_id}' not found — call POST /api/sessions/{agent_id} first",
            )

        loop = asyncio.get_event_loop()
        before = await loop.run_in_executor(None, sup.capture, agent_id, 400)
        await loop.run_in_executor(None, sup.send_prompt, agent_id, body.prompt)

        if not body.wait:
            return {"ok": True, "agent_id": agent_id, "waited": False}

        captured = await loop.run_in_executor(
            None, sup.wait_for_idle, agent_id, body.idle_seconds, body.timeout_seconds, 0.5,
        )
        # Diff the new content from the snapshot taken before send.
        new_text = captured
        if before and before in captured:
            idx = captured.rfind(before)
            new_text = captured[idx + len(before):]

        return {
            "ok": True,
            "agent_id": agent_id,
            "waited": True,
            "response": new_text.strip(),
            "full_capture": captured,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=_typed(e))


# ── capture / stream ────────────────────────────────────────────────────


@router.get("/{agent_id}/capture")
async def capture(agent_id: str, lines: int = Query(default=200, ge=1, le=10000)):
    try:
        sup = get_supervisor()
        if not sup.session_exists(agent_id):
            raise HTTPException(
                status_code=404,
                detail=f"KeyError: tmux session for '{agent_id}' not found",
            )
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(None, sup.capture, agent_id, lines)
        return {"agent_id": agent_id, "lines": lines, "text": text}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=_typed(e))


@router.get("/{agent_id}/stream")
async def stream(agent_id: str, lines: int = Query(default=200, ge=1, le=10000)):
    """SSE stream — emits a `data:` event whenever the captured pane text changes.

    Polls every 500ms; only sends a frame when the text differs from the last one
    so clients don't flood with duplicates.
    """
    sup = get_supervisor()
    if not sup.session_exists(agent_id):
        raise HTTPException(
            status_code=404,
            detail=f"KeyError: tmux session for '{agent_id}' not found",
        )

    async def gen():
        last: Optional[str] = None
        loop = asyncio.get_event_loop()
        try:
            while True:
                try:
                    text = await loop.run_in_executor(None, sup.capture, agent_id, lines)
                except Exception as e:
                    yield f"event: error\ndata: {json.dumps({'error': _typed(e)})}\n\n"
                    return
                if text != last:
                    last = text
                    yield f"data: {json.dumps({'agent_id': agent_id, 'text': text})}\n\n"
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            return

    return StreamingResponse(gen(), media_type="text/event-stream")
