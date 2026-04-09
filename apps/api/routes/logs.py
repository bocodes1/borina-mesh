"""Log file streaming via Server-Sent Events."""

import os
import asyncio
import json
from pathlib import Path
from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

router = APIRouter(prefix="/logs", tags=["logs"])

# Whitelist of log files we're allowed to tail
LOG_SOURCES = {
    "api": "~/borina-mesh/logs/api.log",
    "api-err": "~/borina-mesh/logs/api.err.log",
    "web": "~/borina-mesh/logs/web.log",
    "web-err": "~/borina-mesh/logs/web.err.log",
    "auto-update": "~/borina-mesh/logs/auto-update.log",
    "polymarket-bot": "~/polymarket-bot/logs/bot.log",
    "polymarket-signal": "~/polymarket-bot/logs/signal_engine.log",
}


@router.get("/sources")
async def list_sources():
    """List available log sources and their status."""
    results = []
    for name, path_str in LOG_SOURCES.items():
        path = Path(os.path.expanduser(path_str))
        results.append({
            "name": name,
            "path": str(path),
            "exists": path.exists(),
            "size_bytes": path.stat().st_size if path.exists() else 0,
        })
    return results


@router.get("/stream/{source}")
async def stream_log(source: str, tail_lines: int = 200):
    """Stream a log file live via SSE. Sends last `tail_lines` lines then follows."""
    if source not in LOG_SOURCES:
        raise HTTPException(status_code=404, detail=f"Unknown log source: {source}")

    path = Path(os.path.expanduser(LOG_SOURCES[source]))
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Log file not found: {path}")

    async def event_generator():
        # First, send the last N lines
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
                tail = lines[-tail_lines:] if len(lines) > tail_lines else lines
                for line in tail:
                    yield {"event": "log", "data": json.dumps({"line": line.rstrip()})}

                # Then tail the file for new content
                f.seek(0, 2)  # Seek to end
                while True:
                    line = f.readline()
                    if line:
                        yield {"event": "log", "data": json.dumps({"line": line.rstrip()})}
                    else:
                        await asyncio.sleep(0.5)
        except Exception as e:
            yield {"event": "error", "data": json.dumps({"error": str(e)})}

    return EventSourceResponse(event_generator())
