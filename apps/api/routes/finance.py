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

from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

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
