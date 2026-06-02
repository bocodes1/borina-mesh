"""Market data: quotes, history, fundamentals, news.

Provider-agnostic but defaults to a Finnhub-style free endpoint, keyed by
MARKET_DATA_API_KEY. Read-only. Returns IntegrationResult everywhere.

Tests monkeypatch `http_get_json` (imported below) and set MARKET_DATA_API_KEY
to exercise the connected path; leaving the key unset exercises not-connected.
"""
from __future__ import annotations

from typing import Optional

from .base import IntegrationResult, env, http_get_json, not_connected, ok, safe

SOURCE = "market_data"
BASE_URL = "https://finnhub.io/api/v1"


def _key() -> str:
    return env("MARKET_DATA_API_KEY")


def status() -> IntegrationResult:
    if not _key():
        return not_connected(SOURCE, "MARKET_DATA_API_KEY not set")
    return ok(SOURCE, {"provider": "finnhub", "base_url": BASE_URL})


@safe(SOURCE)
def get_quote(symbol: str) -> IntegrationResult:
    key = _key()
    if not key:
        return not_connected(SOURCE, "MARKET_DATA_API_KEY not set")
    raw = http_get_json(f"{BASE_URL}/quote", params={"symbol": symbol, "token": key})
    # Finnhub quote: c=current, d=change, dp=percent, h/l/o/pc
    price = raw.get("c")
    prev = raw.get("pc")
    data = {
        "symbol": symbol.upper(),
        "price": price,
        "change": raw.get("d"),
        "change_pct": raw.get("dp"),
        "high": raw.get("h"),
        "low": raw.get("l"),
        "open": raw.get("o"),
        "prev_close": prev,
    }
    if price in (None, 0) and not raw:
        return not_connected(SOURCE, f"no quote for {symbol}")
    return ok(SOURCE, data)


@safe(SOURCE)
def get_history(symbol: str, range_: str = "1M") -> IntegrationResult:
    key = _key()
    if not key:
        return not_connected(SOURCE, "MARKET_DATA_API_KEY not set")
    raw = http_get_json(
        f"{BASE_URL}/stock/candle",
        params={"symbol": symbol, "resolution": "D", "token": key, "range": range_},
    )
    closes = raw.get("c") or []
    times = raw.get("t") or []
    points = [{"t": t, "close": c} for t, c in zip(times, closes)]
    return ok(SOURCE, {"symbol": symbol.upper(), "range": range_, "points": points})


@safe(SOURCE)
def get_fundamentals(symbol: str) -> IntegrationResult:
    key = _key()
    if not key:
        return not_connected(SOURCE, "MARKET_DATA_API_KEY not set")
    raw = http_get_json(
        f"{BASE_URL}/stock/metric",
        params={"symbol": symbol, "metric": "all", "token": key},
    )
    m = (raw or {}).get("metric", {}) if isinstance(raw, dict) else {}
    return ok(
        SOURCE,
        {
            "symbol": symbol.upper(),
            "pe": m.get("peTTM"),
            "market_cap": m.get("marketCapitalization"),
            "ev_ebitda": m.get("currentEv/freeCashFlowTTM"),
            "week52_high": m.get("52WeekHigh"),
            "week52_low": m.get("52WeekLow"),
        },
    )


@safe(SOURCE)
def get_news(symbol: str, limit: int = 5) -> IntegrationResult:
    key = _key()
    if not key:
        return not_connected(SOURCE, "MARKET_DATA_API_KEY not set")
    raw = http_get_json(
        f"{BASE_URL}/company-news",
        params={"symbol": symbol, "token": key},
    )
    items = raw if isinstance(raw, list) else []
    news = [
        {
            "title": it.get("headline"),
            "url": it.get("url"),
            "source": it.get("source"),
            "published": it.get("datetime"),
            "summary": it.get("summary"),
        }
        for it in items[:limit]
    ]
    return ok(SOURCE, news)
