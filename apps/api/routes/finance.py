"""Finance routes for the dashboard's Finance tab.

Endpoints:
  GET    /finance/brief                — today's brief (cached, 5am ET)
  POST   /finance/brief/regenerate     — force regenerate (burns Opus quota)
  GET    /finance/watchlist            — list tickers
  POST   /finance/watchlist            — add a ticker (body: {"ticker": "..."})
  DELETE /finance/watchlist/{ticker}   — remove
  GET    /finance/ticker/{symbol}      — deep-dive: 3-lens valuation snapshot
  GET    /finance/status               — config: which keys present, last run
"""

from __future__ import annotations

import asyncio
import json
from datetime import date

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from agents.finance_brief import (
    generate_brief,
    load_cached_brief,
)
from agents.finance_data import (
    DataSourceError,
    FinanceClients,
    load_watchlist,
    save_watchlist,
)
from agents.finance_deepdive import (
    cache_status,
    generate_deepdive,
    get_run_state,
    invalidate_cache,
    load_cached_deepdive,
    split_into_sections,
    STATUS_FRESH,
    STATUS_GENERATING,
    STATUS_NOT_FOUND,
    STATUS_STALE,
)
from agents.finance_screen import _equity_candidate

router = APIRouter(prefix="/finance", tags=["finance"])


def _typed(e: Exception) -> str:
    return f"{type(e).__name__}: {e!r}"


# ────────────────────────────────────────────────────────────────────────────
# Brief
# ────────────────────────────────────────────────────────────────────────────


@router.get("/brief")
async def get_brief():
    """Return today's cached brief. If not yet generated, returns null markdown."""
    cached = load_cached_brief()
    if cached is None:
        return {
            "trading_date": date.today().isoformat(),
            "markdown": None,
            "generated_at": None,
            "error": "Not yet generated today. POST /finance/brief/regenerate to build now.",
        }
    return {
        "trading_date": cached.trading_date,
        "markdown": cached.markdown,
        "generated_at": cached.generated_at,
        "duration_seconds": cached.duration_seconds,
        "error": cached.error,
        "data_source_status": cached.screen.get("data_source_status", {}),
        "skipped_sections": cached.screen.get("skipped_sections", []),
    }


@router.post("/brief/regenerate")
async def regenerate_brief():
    """Force-regenerate today's brief. Burns Opus quota — call sparingly."""
    try:
        brief = await generate_brief(use_cache=False)
    except Exception as e:
        raise HTTPException(status_code=500, detail=_typed(e))
    return {
        "trading_date": brief.trading_date,
        "markdown": brief.markdown,
        "generated_at": brief.generated_at,
        "duration_seconds": brief.duration_seconds,
        "error": brief.error,
    }


# ────────────────────────────────────────────────────────────────────────────
# Watchlist
# ────────────────────────────────────────────────────────────────────────────


class WatchlistAddBody(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=10)


@router.get("/watchlist")
async def watchlist_get():
    return {"tickers": load_watchlist()}


@router.post("/watchlist")
async def watchlist_add(body: WatchlistAddBody):
    ticker = body.ticker.strip().upper()
    if not ticker.replace("-", "").replace(".", "").isalnum():
        raise HTTPException(status_code=400, detail="invalid ticker format")
    current = set(load_watchlist())
    current.add(ticker)
    save_watchlist(list(current))
    return {"tickers": load_watchlist()}


@router.delete("/watchlist/{ticker}")
async def watchlist_remove(ticker: str):
    ticker = ticker.upper()
    current = [t for t in load_watchlist() if t != ticker]
    save_watchlist(current)
    return {"tickers": load_watchlist()}


# ────────────────────────────────────────────────────────────────────────────
# Ticker deep-dive
# ────────────────────────────────────────────────────────────────────────────


@router.get("/ticker/{symbol}")
async def ticker_deepdive(symbol: str):
    """Pull all 3 valuation lenses + recent filings for one ticker.

    Returns the same ValuationSnapshot the screen uses, but for an arbitrary
    user-clicked ticker (not just candidates). If FMP isn't configured,
    returns just the EDGAR filings.
    """
    sym = symbol.upper()
    clients = FinanceClients.default()

    if clients.fmp.configured:
        snap = _equity_candidate(clients, sym)
        if snap is None:
            raise HTTPException(
                status_code=404,
                detail=f"{sym}: no data (or excluded by earnings filter / market cap)",
            )
        from dataclasses import asdict
        return asdict(snap)

    # Degraded mode — EDGAR only.
    try:
        filings = clients.edgar.recent_filings(sym, form_types=("10-K", "10-Q"))
    except DataSourceError as e:
        raise HTTPException(status_code=404, detail=_typed(e))
    return {
        "ticker": sym,
        "warning": "FMP_API_KEY not configured — only filings available, no multiples",
        "recent_filings": filings,
    }


# ────────────────────────────────────────────────────────────────────────────
# Status
# ────────────────────────────────────────────────────────────────────────────


@router.get("/status")
async def status():
    """Health/config snapshot for the dashboard's Settings section."""
    clients = FinanceClients.default()
    cached = load_cached_brief()
    return {
        "data_source_status": clients.configured_summary(),
        "watchlist_size": len(load_watchlist()),
        "last_brief_generated_at": cached.generated_at if cached else None,
        "last_brief_duration_seconds": cached.duration_seconds if cached else None,
        "last_brief_trading_date": cached.trading_date if cached else None,
    }


# ────────────────────────────────────────────────────────────────────────────
# Per-ticker deep-dive
# ────────────────────────────────────────────────────────────────────────────


@router.get("/deepdive/{ticker}/status")
async def deepdive_status(ticker: str):
    """Resolve current cache state. Applies invalidation rules (TTL, new
    8-K, earnings crossed, >5% move). Returns ``STATUS_*``."""
    sym = ticker.upper()
    run = get_run_state(sym)
    if run and run.get("status") == STATUS_GENERATING:
        return {
            "ticker": sym,
            "status": STATUS_GENERATING,
            "phase": run.get("phase"),
            "events": run.get("events", []),
        }
    return {"ticker": sym, **cache_status(sym)}


@router.get("/deepdive/{ticker}")
async def deepdive_get(ticker: str):
    """Return the cached deep-dive markdown + section breakdown, or 404."""
    sym = ticker.upper()
    cached = load_cached_deepdive(sym)
    if cached is None:
        raise HTTPException(
            status_code=404,
            detail=f"No deep-dive cached for {sym}. POST /finance/deepdive/{sym}/generate to build.",
        )
    state = cache_status(sym)
    return {
        "ticker": sym,
        "is_crypto": cached.is_crypto,
        "generated_at": cached.generated_at,
        "ttl_until": cached.ttl_until,
        "duration_seconds": cached.duration_seconds,
        "markdown": cached.markdown,
        "sections": split_into_sections(cached.markdown),
        "error": cached.error,
        "data_source_status": cached.data_source_status,
        "cache_status": state["status"],
        "stale_reason": state.get("stale_reason"),
    }


class GenerateBody(BaseModel):
    force: bool = Field(False, description="Regenerate even if cache is fresh")


@router.post("/deepdive/{ticker}/generate")
async def deepdive_generate(
    ticker: str,
    body: GenerateBody,
    background_tasks: BackgroundTasks,
):
    """Kick off a deep-dive generation in the background. Returns the
    stream URL the frontend should connect to for progress events."""
    sym = ticker.upper()

    state = cache_status(sym)
    if state["status"] == STATUS_FRESH and not body.force:
        return {
            "ticker": sym,
            "status": STATUS_FRESH,
            "stream_url": None,
            "message": "Cache is fresh; pass force=true to regenerate.",
        }

    # Don't double-start a generation already in flight
    run = get_run_state(sym)
    if run and run.get("status") == STATUS_GENERATING:
        return {
            "ticker": sym,
            "status": STATUS_GENERATING,
            "stream_url": f"/api/finance/deepdive/{sym}/stream",
            "message": "Generation already in flight; tail the stream.",
        }

    background_tasks.add_task(_run_generation, sym)
    return {
        "ticker": sym,
        "status": STATUS_GENERATING,
        "stream_url": f"/api/finance/deepdive/{sym}/stream",
        "message": "Generation started.",
    }


async def _run_generation(sym: str) -> None:
    """Background runner — kept thin so HTTPException context isn't needed."""
    try:
        await generate_deepdive(sym, use_cache=False)
    except Exception as e:
        # Status was already flipped to FAILED inside generate_deepdive's
        # exception path. Log here for ops visibility.
        print(f"[finance_deepdive] {sym} generation crashed: {type(e).__name__}: {e!r}")


@router.get("/deepdive/{ticker}/stream")
async def deepdive_stream(ticker: str):
    """SSE stream of generation progress. Emits one event per status flip
    plus a final 'complete' event once the cache is written."""
    sym = ticker.upper()

    async def event_gen():
        seen = 0
        deadline = asyncio.get_event_loop().time() + 60 * 30  # 30 min cap
        while asyncio.get_event_loop().time() < deadline:
            run = get_run_state(sym)
            if run is None:
                # No active run — check if cache landed (would mean a non-tracked completion)
                cached = load_cached_deepdive(sym)
                if cached:
                    yield {
                        "event": "complete",
                        "data": json.dumps({
                            "ticker": sym,
                            "generated_at": cached.generated_at,
                            "duration_seconds": cached.duration_seconds,
                        }),
                    }
                    return
                yield {"event": "waiting", "data": json.dumps({"ticker": sym})}
                await asyncio.sleep(1)
                continue
            events = run.get("events", [])
            while seen < len(events):
                evt = events[seen]
                seen += 1
                payload = {"ticker": sym, **evt}
                yield {"event": evt.get("status", "update"), "data": json.dumps(payload)}
                if evt.get("phase") == "complete":
                    return
            if run.get("status") in (STATUS_FRESH,):
                return
            await asyncio.sleep(1)
        # Timeout
        yield {"event": "timeout", "data": json.dumps({"ticker": sym})}

    return EventSourceResponse(event_gen())


@router.delete("/deepdive/{ticker}/cache")
async def deepdive_invalidate(ticker: str):
    """Force-invalidate a cached deep-dive."""
    sym = ticker.upper()
    removed = invalidate_cache(sym)
    return {"ticker": sym, "removed": removed}
