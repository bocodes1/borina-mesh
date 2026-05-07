"""HTTP API for the tmux/`claude` session pool.

Endpoints (all under `/api/sessions/`):

    GET  /                         → list sessions
    POST /{agent_id}               → spawn a session
    DELETE /{agent_id}             → kill a session
    POST /{agent_id}/restart       → kill + respawn
    POST /{agent_id}/prompt        → send a prompt; if wait=True, block on idle
    GET  /{agent_id}/capture       → pane capture (lines query param)
    GET  /{agent_id}/stream        → SSE pane stream (emits on change)

All errors are normalised to `{"detail": "TypeName: <repr>"}` so callers can
parse error class instead of mining freeform strings.
"""

from __future__ import annotations

import asyncio
import json
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agents.runner_v2 import run_agent_task, AGENT_REGISTRY, _canonical_agent_id
from agents.tmux_supervisor import get_supervisor


router = APIRouter()


# ----------------------------------------------------------------------------
# Request models
# ----------------------------------------------------------------------------

class SpawnBody(BaseModel):
    workdir: str = Field(..., description="Absolute path to use as the agent's CWD")
    system_prompt: str = Field("", description="System prompt appended to claude")


class PromptBody(BaseModel):
    prompt: str = Field(..., description="The user prompt to send")
    wait: bool = Field(True, description="If true, block until response is idle")
    idle_seconds: float = Field(4.0, description="Idle window that signals 'done'")
    timeout_seconds: float = Field(600.0, description="Max wall time before partial return")
    fresh_context: bool = Field(False, description="Restart session before sending")


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def _typed_detail(e: BaseException) -> str:
    return f"{type(e).__name__}: {e!r}"


def _http_500(e: BaseException) -> HTTPException:
    return HTTPException(status_code=500, detail=_typed_detail(e))


def _http_404(detail: str) -> HTTPException:
    return HTTPException(status_code=404, detail=detail)


# ----------------------------------------------------------------------------
# Endpoints
# ----------------------------------------------------------------------------

@router.get("")
@router.get("/")
def list_sessions():
    """List all sessions known to the supervisor."""
    sup = get_supervisor()
    try:
        return {"sessions": sup.list_sessions()}
    except Exception as e:
        raise _http_500(e)


@router.post("/{agent_id}")
def spawn_session(agent_id: str, body: SpawnBody):
    """Spawn (or re-adopt) the agent's tmux/claude session."""
    sup = get_supervisor()
    canonical = _canonical_agent_id(agent_id)
    try:
        info = sup.spawn(canonical, body.workdir, body.system_prompt)
        return {"ok": True, **info}
    except Exception as e:
        raise _http_500(e)


@router.delete("/{agent_id}")
def kill_session(agent_id: str):
    """Kill the agent's tmux session and forget it."""
    sup = get_supervisor()
    canonical = _canonical_agent_id(agent_id)
    try:
        info = sup.kill(canonical)
        return {"ok": True, **info}
    except RuntimeError as e:
        # "agent X is not known" → 404, anything else → 500.
        msg = str(e)
        if "not known" in msg or "not running" in msg:
            raise _http_404(_typed_detail(e))
        raise _http_500(e)
    except Exception as e:
        raise _http_500(e)


@router.post("/{agent_id}/restart")
def restart_session(agent_id: str):
    """Kill and respawn the agent's session, preserving workdir/system_prompt."""
    sup = get_supervisor()
    canonical = _canonical_agent_id(agent_id)
    try:
        info = sup.restart(canonical)
        return {"ok": True, **info}
    except RuntimeError as e:
        msg = str(e)
        if "not known" in msg:
            raise _http_404(_typed_detail(e))
        raise _http_500(e)
    except Exception as e:
        raise _http_500(e)


@router.post("/{agent_id}/prompt")
async def post_prompt(agent_id: str, body: PromptBody):
    """Send a prompt to the agent's session.

    If wait=True (default), block until the response is idle and return the
    captured output. If wait=False, fire-and-forget.
    """
    sup = get_supervisor()
    canonical = _canonical_agent_id(agent_id)

    if body.wait:
        # Use the runner so spawn-if-needed + diff-extraction logic stays in
        # one place. This is the "round-trip" path used in verification.
        result = await run_agent_task(
            canonical,
            body.prompt,
            timeout_seconds=body.timeout_seconds,
            idle_seconds=body.idle_seconds,
            fresh_context=body.fresh_context,
        )
        if not result.ok and not result.output:
            # Surface the typed error to the caller.
            raise HTTPException(status_code=500, detail=result.error)
        return {
            "ok": result.ok,
            "agent_id": result.agent_id,
            "output": result.output,
            "timed_out": result.timed_out,
            "elapsed_seconds": result.elapsed_seconds,
            "metadata": result.metadata,
            "error": result.error or None,
        }

    # Fire-and-forget: just send. Spawn first if needed.
    def _send_fire_and_forget():
        if not sup.session_exists(canonical):
            from agents.runner_v2 import _agent_workdir, _resolve_system_prompt
            sup.spawn(
                canonical,
                str(_agent_workdir(canonical)),
                _resolve_system_prompt(canonical),
            )
        sup.send_prompt(canonical, body.prompt)

    try:
        await asyncio.get_event_loop().run_in_executor(None, _send_fire_and_forget)
        return {"ok": True, "agent_id": agent_id, "queued": True}
    except Exception as e:
        raise _http_500(e)


@router.get("/{agent_id}/capture")
def capture_pane(agent_id: str, lines: int = Query(200, ge=1, le=10000)):
    """Capture the last N lines of the agent's pane (ANSI stripped)."""
    sup = get_supervisor()
    canonical = _canonical_agent_id(agent_id)
    try:
        text = sup.capture(canonical, lines=lines)
        return {"agent_id": agent_id, "lines": lines, "text": text}
    except RuntimeError as e:
        msg = str(e)
        if "not known" in msg or "not running" in msg:
            raise _http_404(_typed_detail(e))
        raise _http_500(e)
    except Exception as e:
        raise _http_500(e)


@router.get("/{agent_id}/stream")
async def stream_pane(agent_id: str, lines: int = Query(200, ge=1, le=10000)):
    """Server-Sent Events stream of pane changes.

    Polls capture() every 500ms and emits a `data:` event only when the
    captured text changes. Sends an initial `:keepalive` comment so clients
    know the connection is live.
    """
    sup = get_supervisor()
    canonical = _canonical_agent_id(agent_id)

    async def _gen():
        loop = asyncio.get_event_loop()
        last: Optional[str] = None
        # Initial comment so the connection is observable as 'open' immediately.
        yield ":keepalive\n\n"
        while True:
            try:
                current = await loop.run_in_executor(
                    None, lambda: sup.capture(canonical, lines=lines)
                )
            except RuntimeError as e:
                payload = json.dumps({"error": _typed_detail(e)})
                yield f"event: error\ndata: {payload}\n\n"
                return
            except Exception as e:
                payload = json.dumps({"error": _typed_detail(e)})
                yield f"event: error\ndata: {payload}\n\n"
                return

            if current != last:
                last = current
                payload = json.dumps({"text": current})
                yield f"data: {payload}\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(_gen(), media_type="text/event-stream")
