"""Data connectors for the Finance agent.

Five sources, one client class each. Each gracefully reports missing API keys
rather than raising — the screen function decides whether a missing source is
fatal or just means a lens gets skipped.

Sources:
- SEC EDGAR (free, requires User-Agent) — official filings
- FRED (free key) — macro context
- Financial Modeling Prep (paid) — fundamentals + peers + earnings calendar
- Polygon.io (paid) — price/volume history
- CoinGecko (free) — crypto majors

All clients are sync because the screen runs on a scheduler thread and the
APIs are HTTP/JSON. If the brief generation latency becomes a problem, swap
to httpx.AsyncClient — interface stays the same.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import httpx


# ────────────────────────────────────────────────────────────────────────────
# Watchlist
# ────────────────────────────────────────────────────────────────────────────

WATCHLIST_PATH = Path.home() / ".borina" / "data" / "watchlist.json"


def load_watchlist() -> list[str]:
    """Read the user's watchlist tickers. Auto-creates a stub on first run."""
    if not WATCHLIST_PATH.exists():
        WATCHLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        WATCHLIST_PATH.write_text('["NVDA", "TSLA", "ASML"]\n', encoding="utf-8")
    try:
        data = json.loads(WATCHLIST_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []
        return [str(t).upper() for t in data if isinstance(t, str) and t.strip()]
    except (OSError, json.JSONDecodeError):
        return []


def save_watchlist(tickers: list[str]) -> None:
    """Persist the watchlist atomically."""
    WATCHLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    cleaned = sorted({t.upper().strip() for t in tickers if t and t.strip()})
    tmp = WATCHLIST_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cleaned) + "\n", encoding="utf-8")
    tmp.replace(WATCHLIST_PATH)


# ────────────────────────────────────────────────────────────────────────────
# Common error type
# ────────────────────────────────────────────────────────────────────────────


class DataSourceError(RuntimeError):
    """Raised when a data source can't fulfil a request.

    The .reason attribute is one of: "missing_key", "rate_limited",
    "not_found", "http_error", "parse_error", "transport_error".
    """

    def __init__(self, source: str, reason: str, detail: str = ""):
        super().__init__(f"{source}: {reason} ({detail})" if detail else f"{source}: {reason}")
        self.source = source
        self.reason = reason
        self.detail = detail


# ────────────────────────────────────────────────────────────────────────────
# SEC EDGAR — official filings (free, requires User-Agent header)
# ────────────────────────────────────────────────────────────────────────────


class EdgarClient:
    """Read-only client for SEC EDGAR data API.

    No API key required, but the SEC enforces a User-Agent header containing
    a contact email. Set SEC_EDGAR_USER_AGENT in .env. Default 10 req/sec
    fair-use limit — we self-rate-limit at the call site.
    """

    BASE = "https://data.sec.gov"

    def __init__(self) -> None:
        ua = os.environ.get("SEC_EDGAR_USER_AGENT", "").strip()
        if not ua:
            ua = "Borina Mesh research@example.com"
        self._client = httpx.Client(
            headers={"User-Agent": ua, "Accept": "application/json"},
            timeout=30.0,
        )
        self._last_call = 0.0

    def _throttle(self) -> None:
        # SEC asks for ≤10 req/sec; we throttle to 7 to leave headroom.
        gap = time.time() - self._last_call
        if gap < 0.15:
            time.sleep(0.15 - gap)
        self._last_call = time.time()

    def _get_json(self, url: str) -> dict:
        self._throttle()
        try:
            r = self._client.get(url)
        except httpx.HTTPError as e:
            raise DataSourceError("edgar", "transport_error", str(e)) from e
        if r.status_code == 404:
            raise DataSourceError("edgar", "not_found", url)
        if r.status_code == 429:
            raise DataSourceError("edgar", "rate_limited", url)
        if r.status_code >= 400:
            raise DataSourceError("edgar", "http_error", f"{r.status_code} {url}")
        try:
            return r.json()
        except ValueError as e:
            raise DataSourceError("edgar", "parse_error", str(e)) from e

    def lookup_cik(self, ticker: str) -> Optional[str]:
        """Resolve a stock ticker to its 10-digit zero-padded CIK."""
        # SEC's ticker→CIK lookup file is small (~3 MB) and updated daily.
        url = "https://www.sec.gov/files/company_tickers.json"
        data = self._get_json(url)
        ticker_upper = ticker.upper()
        for entry in data.values():
            if entry.get("ticker", "").upper() == ticker_upper:
                return f"{int(entry['cik_str']):010d}"
        return None

    def recent_filings(self, ticker: str, form_types: tuple[str, ...] = ("10-K", "10-Q")) -> list[dict]:
        """Return the most recent filings of given form types for a ticker.

        Each filing is a dict with: form, filing_date, accession_number,
        primary_doc, primary_doc_url.
        """
        cik = self.lookup_cik(ticker)
        if not cik:
            raise DataSourceError("edgar", "not_found", f"no CIK for {ticker}")
        sub = self._get_json(f"{self.BASE}/submissions/CIK{cik}.json")
        recent = sub.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])
        primary_docs = recent.get("primaryDocument", [])
        out = []
        cik_int = int(cik)
        for i, form in enumerate(forms):
            if form not in form_types:
                continue
            acc = accessions[i] if i < len(accessions) else ""
            acc_compact = acc.replace("-", "")
            doc = primary_docs[i] if i < len(primary_docs) else ""
            out.append({
                "form": form,
                "filing_date": dates[i] if i < len(dates) else "",
                "accession_number": acc,
                "primary_doc": doc,
                "primary_doc_url": (
                    f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_compact}/{doc}"
                    if acc_compact and doc else ""
                ),
            })
            if len(out) >= 6:  # cap — caller usually wants the last 1-2
                break
        return out

    def thirteen_f_changes(self, ticker: str) -> list[dict]:
        """Net adds/trims from 13F filings — placeholder.

        Aggregating 13F holders by ticker requires a different endpoint
        (the institutional ownership query) and significant post-processing.
        Stub for now — returns []. Wire later if FMP's institutional-ownership
        feed isn't sufficient.
        """
        return []

    def filings_full(
        self,
        ticker: str,
        form_types: tuple[str, ...] = ("10-K", "10-Q", "8-K", "DEF 14A"),
        days_back: int = 180,
    ) -> list[dict]:
        """All filings of given form types in the last N days.

        Different from `recent_filings` (which caps at 6 entries): this returns
        the full set inside a date window, used by the deep-dive's "recent
        filings (last 90 days)" section.
        """
        cik = self.lookup_cik(ticker)
        if not cik:
            raise DataSourceError("edgar", "not_found", f"no CIK for {ticker}")
        sub = self._get_json(f"{self.BASE}/submissions/CIK{cik}.json")
        recent = sub.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])
        primary_docs = recent.get("primaryDocument", [])
        cutoff = date.today() - timedelta(days=days_back)
        cik_int = int(cik)
        out = []
        for i, form in enumerate(forms):
            if form not in form_types:
                continue
            try:
                fd = date.fromisoformat(dates[i])
            except (ValueError, IndexError):
                continue
            if fd < cutoff:
                continue
            acc = accessions[i] if i < len(accessions) else ""
            acc_compact = acc.replace("-", "")
            doc = primary_docs[i] if i < len(primary_docs) else ""
            out.append({
                "form": form,
                "filing_date": dates[i],
                "accession_number": acc,
                "primary_doc": doc,
                "primary_doc_url": (
                    f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_compact}/{doc}"
                    if acc_compact and doc else ""
                ),
            })
        return out

    def form4_activity(self, ticker: str, days_back: int = 180) -> list[dict]:
        """Form 4 (insider trading) filings in the last N days.

        EDGAR's submissions endpoint includes Form 4s mixed with everything
        else. We filter and surface them here. Deep-dive uses this when FMP's
        insider feed is unavailable.
        """
        return self.filings_full(ticker, form_types=("4",), days_back=days_back)


# ────────────────────────────────────────────────────────────────────────────
# FRED — macro context (free key required)
# ────────────────────────────────────────────────────────────────────────────


class FredClient:
    BASE = "https://api.stlouisfed.org/fred"

    SERIES = {
        "treasury_10y": "DGS10",
        "fed_funds": "DFF",
        "vix": "VIXCLS",
        "dxy": "DTWEXBGS",  # broad dollar index
    }

    def __init__(self) -> None:
        self._key = os.environ.get("FRED_API_KEY", "").strip()
        self._client = httpx.Client(timeout=15.0)

    @property
    def configured(self) -> bool:
        return bool(self._key)

    def latest(self, series_key: str) -> tuple[date, float]:
        """Latest observation for a named series. Returns (date, value)."""
        if not self._key:
            raise DataSourceError("fred", "missing_key", "set FRED_API_KEY in .env")
        series_id = self.SERIES.get(series_key, series_key)
        try:
            r = self._client.get(
                f"{self.BASE}/series/observations",
                params={
                    "series_id": series_id,
                    "api_key": self._key,
                    "file_type": "json",
                    "sort_order": "desc",
                    "limit": 1,
                },
            )
        except httpx.HTTPError as e:
            raise DataSourceError("fred", "transport_error", str(e)) from e
        if r.status_code >= 400:
            raise DataSourceError("fred", "http_error", f"{r.status_code}")
        obs = r.json().get("observations", [])
        if not obs:
            raise DataSourceError("fred", "not_found", series_id)
        latest = obs[0]
        try:
            return date.fromisoformat(latest["date"]), float(latest["value"])
        except (KeyError, ValueError) as e:
            raise DataSourceError("fred", "parse_error", str(e)) from e

    def macro_snapshot(self) -> dict:
        """One-shot snapshot of all 4 macro series. Failures return None per key."""
        out: dict[str, Optional[dict]] = {}
        for key in self.SERIES:
            try:
                d, v = self.latest(key)
                out[key] = {"date": d.isoformat(), "value": v}
            except DataSourceError as e:
                out[key] = {"error": e.reason}
        return out


# ────────────────────────────────────────────────────────────────────────────
# Financial Modeling Prep — fundamentals (paid)
# ────────────────────────────────────────────────────────────────────────────


class FmpClient:
    BASE = "https://financialmodelingprep.com/api/v3"
    BASE_V4 = "https://financialmodelingprep.com/api/v4"

    def __init__(self) -> None:
        self._key = os.environ.get("FMP_API_KEY", "").strip()
        self._client = httpx.Client(timeout=20.0)

    @property
    def configured(self) -> bool:
        return bool(self._key)

    def _get(self, path: str, *, base: str = BASE, **params) -> Any:
        if not self._key:
            raise DataSourceError("fmp", "missing_key", "set FMP_API_KEY in .env")
        params["apikey"] = self._key
        try:
            r = self._client.get(f"{base}/{path}", params=params)
        except httpx.HTTPError as e:
            raise DataSourceError("fmp", "transport_error", str(e)) from e
        if r.status_code == 429:
            raise DataSourceError("fmp", "rate_limited", path)
        if r.status_code >= 400:
            raise DataSourceError("fmp", "http_error", f"{r.status_code} {path}")
        try:
            return r.json()
        except ValueError as e:
            raise DataSourceError("fmp", "parse_error", str(e)) from e

    def quote(self, ticker: str) -> dict:
        """Latest quote: price, market cap, P/E, EPS, change %."""
        data = self._get(f"quote/{ticker}")
        if isinstance(data, list) and data:
            return data[0]
        raise DataSourceError("fmp", "not_found", ticker)

    def key_metrics_ttm(self, ticker: str) -> dict:
        """Trailing-twelve-month metrics: P/E, EV/EBITDA, P/S, etc."""
        data = self._get(f"key-metrics-ttm/{ticker}")
        if isinstance(data, list) and data:
            return data[0]
        raise DataSourceError("fmp", "not_found", ticker)

    def key_metrics_history(self, ticker: str, years: int = 10) -> list[dict]:
        """Annual key metrics for the last N years (for 5/10-year medians)."""
        data = self._get(f"key-metrics/{ticker}", limit=years)
        if isinstance(data, list):
            return data
        raise DataSourceError("fmp", "parse_error", str(type(data)))

    def income_statement_history(self, ticker: str, years: int = 5) -> list[dict]:
        """Annual income statements — for revenue/margin trajectory."""
        data = self._get(f"income-statement/{ticker}", limit=years)
        if isinstance(data, list):
            return data
        raise DataSourceError("fmp", "parse_error", str(type(data)))

    def peers(self, ticker: str) -> list[str]:
        """3-5 closest competitors by FMP's classification."""
        data = self._get(f"stock_peers", base=self.BASE_V4, symbol=ticker)
        if isinstance(data, list) and data:
            entry = data[0] if isinstance(data[0], dict) else {}
            return list(entry.get("peersList", []))[:5]
        return []

    def earnings_calendar(self, ticker: str) -> Optional[date]:
        """Next earnings date for a ticker, or None if none upcoming."""
        today = date.today().isoformat()
        future = (date.today() + timedelta(days=120)).isoformat()
        data = self._get("earning_calendar", **{"from": today, "to": future, "symbol": ticker})
        if isinstance(data, list) and data:
            try:
                return date.fromisoformat(data[0].get("date", "")[:10])
            except ValueError:
                return None
        return None

    def days_to_earnings(self, ticker: str) -> Optional[int]:
        """Days until next earnings, or None if unknown."""
        d = self.earnings_calendar(ticker)
        if d is None:
            return None
        return (d - date.today()).days

    def institutional_ownership_change(self, ticker: str) -> list[dict]:
        """Latest 13F-derived ownership changes (top adders/trimmers)."""
        try:
            data = self._get(
                "institutional-ownership/symbol-ownership",
                base=self.BASE_V4,
                symbol=ticker,
                includeCurrentQuarter="true",
            )
        except DataSourceError:
            return []
        if isinstance(data, list):
            return data[:1]  # latest quarter snapshot only
        return []

    # ── Deep-dive additions ──────────────────────────────────────────────

    def transcript(self, ticker: str, year: Optional[int] = None, quarter: Optional[int] = None) -> dict:
        """Earnings call transcript. Default: latest available.

        FMP requires the $30+/mo plan for transcripts. On free/basic plans
        this raises DataSourceError("missing_plan") — the caller should
        skip the transcript section gracefully.
        """
        params = {}
        if year is not None:
            params["year"] = year
        if quarter is not None:
            params["quarter"] = quarter
        data = self._get(f"earning_call_transcript/{ticker}", **params)
        if isinstance(data, list) and data:
            return data[0]
        if isinstance(data, dict):
            return data
        raise DataSourceError("fmp", "missing_plan", "transcripts require FMP $30+/mo plan")

    def earnings_history(self, ticker: str, quarters: int = 4) -> list[dict]:
        """Last N quarters of reported vs estimated EPS + revenue."""
        data = self._get(f"earnings-surprises/{ticker}")
        if isinstance(data, list):
            return data[:quarters]
        raise DataSourceError("fmp", "parse_error", str(type(data)))

    def analyst_estimates(self, ticker: str) -> dict:
        """Consensus + revisions trend. Returns target_low/median/high + rev counts."""
        try:
            estimates = self._get(f"analyst-estimates/{ticker}", limit=4)
            recs = self._get(f"upgrades-downgrades-consensus/{ticker}")
        except DataSourceError:
            raise
        consensus = recs[0] if isinstance(recs, list) and recs else {}
        return {
            "consensus_recommendation": consensus.get("consensus"),
            "strongBuy": consensus.get("strongBuy"),
            "buy": consensus.get("buy"),
            "hold": consensus.get("hold"),
            "sell": consensus.get("sell"),
            "strongSell": consensus.get("strongSell"),
            "annual_estimates": estimates if isinstance(estimates, list) else [],
        }

    def upgrades_downgrades(self, ticker: str, limit: int = 20) -> list[dict]:
        """Recent sell-side upgrades/downgrades."""
        try:
            data = self._get(
                "upgrades-downgrades",
                base=self.BASE_V4,
                symbol=ticker,
                limit=limit,
            )
        except DataSourceError:
            return []
        return data if isinstance(data, list) else []

    def institutional_holders(self, ticker: str, top_n: int = 10) -> list[dict]:
        """Top N institutional holders + position size from 13F."""
        try:
            data = self._get(f"institutional-holder/{ticker}")
        except DataSourceError:
            return []
        if isinstance(data, list):
            # FMP returns a flat list — sort by value/shares descending
            sorted_holders = sorted(
                data,
                key=lambda h: h.get("shares") or 0,
                reverse=True,
            )
            return sorted_holders[:top_n]
        return []

    def insider_trades(self, ticker: str, days_back: int = 180) -> list[dict]:
        """Form 4 transactions in the last N days."""
        try:
            data = self._get(
                "insider-trading",
                base=self.BASE_V4,
                symbol=ticker,
                page=0,
            )
        except DataSourceError:
            return []
        if not isinstance(data, list):
            return []
        cutoff = date.today() - timedelta(days=days_back)
        recent: list[dict] = []
        for tx in data:
            try:
                tx_date = date.fromisoformat((tx.get("transactionDate") or "")[:10])
                if tx_date >= cutoff:
                    recent.append(tx)
            except ValueError:
                continue
        return recent

    def segment_breakdown(self, ticker: str) -> dict:
        """Revenue by segment + by geography (latest annual)."""
        try:
            by_segment = self._get(
                f"revenue-product-segmentation",
                base=self.BASE_V4,
                symbol=ticker,
                structure="flat",
                period="annual",
            )
            by_region = self._get(
                f"revenue-geographic-segmentation",
                base=self.BASE_V4,
                symbol=ticker,
                structure="flat",
                period="annual",
            )
        except DataSourceError:
            return {"segments": {}, "regions": {}}
        latest_segment = by_segment[0] if isinstance(by_segment, list) and by_segment else {}
        latest_region = by_region[0] if isinstance(by_region, list) and by_region else {}
        return {
            "segments": next(iter(latest_segment.values()), {}) if latest_segment else {},
            "regions": next(iter(latest_region.values()), {}) if latest_region else {},
        }

    def company_profile(self, ticker: str) -> dict:
        """Company profile: sector, industry, description, website, employees."""
        data = self._get(f"profile/{ticker}")
        if isinstance(data, list) and data:
            return data[0]
        raise DataSourceError("fmp", "not_found", ticker)


# ────────────────────────────────────────────────────────────────────────────
# Polygon.io — price/volume (paid)
# ────────────────────────────────────────────────────────────────────────────


class PolygonClient:
    BASE = "https://api.polygon.io"

    def __init__(self) -> None:
        self._key = os.environ.get("POLYGON_API_KEY", "").strip()
        self._client = httpx.Client(timeout=20.0)

    @property
    def configured(self) -> bool:
        return bool(self._key)

    def _get(self, path: str, **params) -> Any:
        if not self._key:
            raise DataSourceError("polygon", "missing_key", "set POLYGON_API_KEY in .env")
        params["apiKey"] = self._key
        try:
            r = self._client.get(f"{self.BASE}/{path}", params=params)
        except httpx.HTTPError as e:
            raise DataSourceError("polygon", "transport_error", str(e)) from e
        if r.status_code == 429:
            raise DataSourceError("polygon", "rate_limited", path)
        if r.status_code >= 400:
            raise DataSourceError("polygon", "http_error", f"{r.status_code} {path}")
        try:
            return r.json()
        except ValueError as e:
            raise DataSourceError("polygon", "parse_error", str(e)) from e

    def daily_aggregates(self, ticker: str, days: int = 30) -> list[dict]:
        """Daily OHLCV bars for the last N trading days."""
        end = date.today()
        start = end - timedelta(days=int(days * 1.6) + 7)  # buffer for weekends
        data = self._get(
            f"v2/aggs/ticker/{ticker.upper()}/range/1/day/{start.isoformat()}/{end.isoformat()}",
            adjusted="true",
            sort="desc",
            limit=days,
        )
        return data.get("results", []) or []

    def yesterday_change(self, ticker: str) -> Optional[dict]:
        """Yesterday's % move + volume vs 30d avg.

        Returns dict with: ticker, change_pct, volume, avg_volume_30d,
        volume_ratio. None if no data.
        """
        bars = self.daily_aggregates(ticker, days=30)
        if len(bars) < 2:
            return None
        latest, prior = bars[0], bars[1]
        try:
            change_pct = (latest["c"] / prior["c"] - 1) * 100
            volumes = [b["v"] for b in bars if "v" in b]
            avg_vol = sum(volumes) / len(volumes) if volumes else 0
            return {
                "ticker": ticker.upper(),
                "close": latest["c"],
                "change_pct": round(change_pct, 2),
                "volume": latest.get("v", 0),
                "avg_volume_30d": int(avg_vol),
                "volume_ratio": round(latest.get("v", 0) / avg_vol, 2) if avg_vol else 0,
                "as_of": datetime.fromtimestamp(latest["t"] / 1000).date().isoformat(),
            }
        except (KeyError, ZeroDivisionError, TypeError):
            return None


# ────────────────────────────────────────────────────────────────────────────
# CoinGecko — crypto majors (free)
# ────────────────────────────────────────────────────────────────────────────


class CoinGeckoClient:
    BASE = "https://api.coingecko.com/api/v3"
    SYMBOL_TO_ID = {
        "BTC": "bitcoin",
        "ETH": "ethereum",
        "SOL": "solana",
    }

    def __init__(self) -> None:
        self._client = httpx.Client(timeout=15.0)
        # CoinGecko free tier: 30 calls/min. Self-throttle.
        self._last_call = 0.0

    def _throttle(self) -> None:
        gap = time.time() - self._last_call
        if gap < 2.1:  # ~28 req/min
            time.sleep(2.1 - gap)
        self._last_call = time.time()

    def market(self, symbol: str) -> dict:
        """Market data for a major crypto symbol (BTC/ETH/SOL/etc)."""
        coin_id = self.SYMBOL_TO_ID.get(symbol.upper(), symbol.lower())
        self._throttle()
        try:
            r = self._client.get(
                f"{self.BASE}/coins/markets",
                params={"vs_currency": "usd", "ids": coin_id},
            )
        except httpx.HTTPError as e:
            raise DataSourceError("coingecko", "transport_error", str(e)) from e
        if r.status_code == 429:
            raise DataSourceError("coingecko", "rate_limited", symbol)
        if r.status_code >= 400:
            raise DataSourceError("coingecko", "http_error", f"{r.status_code}")
        data = r.json()
        if not isinstance(data, list) or not data:
            raise DataSourceError("coingecko", "not_found", symbol)
        return data[0]

    def candidates_over_threshold(self, market_cap_usd: float = 5_000_000_000) -> list[dict]:
        """Crypto majors above the threshold market cap."""
        out = []
        for sym in ("BTC", "ETH", "SOL"):
            try:
                m = self.market(sym)
                if m.get("market_cap", 0) >= market_cap_usd:
                    out.append({
                        "symbol": sym,
                        "name": m.get("name", sym),
                        "price": m.get("current_price"),
                        "market_cap": m.get("market_cap"),
                        "change_24h_pct": m.get("price_change_percentage_24h"),
                    })
            except DataSourceError:
                continue
        return out


# ────────────────────────────────────────────────────────────────────────────
# Convenience facade
# ────────────────────────────────────────────────────────────────────────────


@dataclass
class FinanceClients:
    """Single bag of clients to pass into the screen function."""

    edgar: EdgarClient
    fred: FredClient
    fmp: FmpClient
    polygon: PolygonClient
    coingecko: CoinGeckoClient

    @classmethod
    def default(cls) -> "FinanceClients":
        return cls(
            edgar=EdgarClient(),
            fred=FredClient(),
            fmp=FmpClient(),
            polygon=PolygonClient(),
            coingecko=CoinGeckoClient(),
        )

    def configured_summary(self) -> dict[str, bool]:
        return {
            "edgar": True,  # no key needed
            "fred": self.fred.configured,
            "fmp": self.fmp.configured,
            "polygon": self.polygon.configured,
            "coingecko": True,  # no key needed
        }


# ────────────────────────────────────────────────────────────────────────────
# Sector → FRED-series mapping for the deep-dive's macro context
# ────────────────────────────────────────────────────────────────────────────


SECTOR_MACRO_DRIVERS: dict[str, list[str]] = {
    # Each entry maps a sector to FRED series IDs that historically matter
    # most for revenue/margin trajectory. The agent uses these to write
    # section 7's "macro exposure" subsection.
    "Technology":              ["DGS10", "DTWEXBGS"],            # rates, dollar
    "Information Technology":  ["DGS10", "DTWEXBGS"],
    "Communication Services":  ["DGS10", "VIXCLS"],
    "Consumer Cyclical":       ["UMCSENT", "DGS10"],             # sentiment, rates
    "Consumer Discretionary":  ["UMCSENT", "DGS10"],
    "Consumer Defensive":      ["CPIAUCSL"],                     # CPI
    "Consumer Staples":        ["CPIAUCSL"],
    "Healthcare":              ["DGS10"],
    "Financial Services":      ["DGS10", "T10Y2Y", "DFF"],       # yield curve
    "Financials":              ["DGS10", "T10Y2Y", "DFF"],
    "Energy":                  ["DCOILWTICO", "DTWEXBGS"],       # WTI, dollar
    "Industrials":             ["INDPRO", "DGS10"],              # industrial production
    "Basic Materials":         ["INDPRO", "DTWEXBGS"],
    "Real Estate":             ["DGS10", "MORTGAGE30US"],
    "Utilities":               ["DGS10"],
}


def macro_drivers_for(sector: str) -> list[str]:
    """Return FRED series IDs that matter most for a given sector."""
    if not sector:
        return ["DGS10"]
    return SECTOR_MACRO_DRIVERS.get(sector, ["DGS10"])


# ────────────────────────────────────────────────────────────────────────────
# Per-call TTL cache — keeps deep-dive regenerations from re-hitting every API
# ────────────────────────────────────────────────────────────────────────────


class _TTLCache:
    """Tiny in-memory TTL cache shared across deep-dive regenerations.

    Not persisted: process restart clears it. Sufficient for the use case —
    a deep-dive's data calls during a single regeneration won't span restarts.
    """

    def __init__(self) -> None:
        self._store: dict[tuple[str, tuple], tuple[float, object]] = {}

    def get(self, fn_name: str, args: tuple, ttl_seconds: float) -> Optional[object]:
        key = (fn_name, args)
        entry = self._store.get(key)
        if not entry:
            return None
        ts, value = entry
        if time.time() - ts > ttl_seconds:
            self._store.pop(key, None)
            return None
        return value

    def put(self, fn_name: str, args: tuple, value: object) -> None:
        self._store[(fn_name, args)] = (time.time(), value)


_data_cache = _TTLCache()


# Per-data-type TTLs, in seconds.
TTL_PRICE = 300        # 5 min
TTL_FILINGS = 3600     # 1 hr
TTL_FUNDAMENTALS = 21600  # 6 hr
TTL_MACRO = 3600       # 1 hr
TTL_TRANSCRIPTS = 86400   # 24 hr


def cached(fn_name: str, ttl: float):
    """Decorator factory: cache `fn(*args)` for `ttl` seconds keyed on args."""
    def deco(fn):
        def wrapper(*args, **kwargs):
            key_args = args + tuple(sorted(kwargs.items()))
            hit = _data_cache.get(fn_name, key_args, ttl)
            if hit is not None:
                return hit
            value = fn(*args, **kwargs)
            _data_cache.put(fn_name, key_args, value)
            return value
        return wrapper
    return deco
