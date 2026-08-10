"""Per-ticker deep-dive: gather data, run the agent, cache, invalidate.

Different from the morning brief:
- One ticker at a time, longer comprehensive output (~3,000 words)
- On-demand (not scheduled), 6-hour TTL cache
- Auto-invalidates on: new 8-K, earnings crossed, intraday >5% move
- SSE-streamed progress so the user sees status flips, not a 60s spinner
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, asdict, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from agents.finance_data import (
    DataSourceError,
    FinanceClients,
    macro_drivers_for,
    cached,
    TTL_PRICE,
    TTL_FILINGS,
    TTL_FUNDAMENTALS,
    TTL_MACRO,
    TTL_TRANSCRIPTS,
)
from agents.finance_brief import _clean_brief_output


CACHE_DIR = Path.home() / ".borina" / "data" / "finance" / "deepdive_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

CACHE_TTL_HOURS = 6
INVALIDATE_PRICE_MOVE_PCT = 5.0


# Crypto symbols handled by the crypto format; everything else is treated as
# an equity ticker.
_CRYPTO_SYMBOLS = {"BTC", "ETH", "SOL"}


# ────────────────────────────────────────────────────────────────────────────
# Status state machine
# ────────────────────────────────────────────────────────────────────────────


STATUS_NOT_FOUND = "not_found"
STATUS_GENERATING = "generating"
STATUS_FRESH = "cached_fresh"
STATUS_STALE = "cached_stale"
STATUS_FAILED = "failed"


# In-process registry of in-flight generations and their progress so the SSE
# stream endpoint can tail them. {ticker: {"status": str, "events": list}}.
_active_runs: dict[str, dict] = {}
_active_runs_lock = asyncio.Lock()


# ────────────────────────────────────────────────────────────────────────────
# Cache shape
# ────────────────────────────────────────────────────────────────────────────


@dataclass
class DeepDiveCache:
    ticker: str
    is_crypto: bool
    generated_at: str  # ISO timestamp
    ttl_until: str     # ISO timestamp
    duration_seconds: float
    markdown: str
    error: Optional[str] = None
    # Snapshots used at generation time, kept so we can detect events that
    # should invalidate the cache without regenerating.
    snapshot: dict = field(default_factory=dict)
    data_source_status: dict = field(default_factory=dict)

    def is_fresh(self) -> bool:
        try:
            ttl_dt = datetime.fromisoformat(self.ttl_until)
        except ValueError:
            return False
        return datetime.now(timezone.utc) < ttl_dt


def _cache_path(ticker: str) -> Path:
    return CACHE_DIR / f"{ticker.upper()}.json"


def load_cached_deepdive(ticker: str) -> Optional[DeepDiveCache]:
    p = _cache_path(ticker)
    if not p.exists():
        return None
    try:
        return DeepDiveCache(**json.loads(p.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def save_cached_deepdive(cache: DeepDiveCache) -> Path:
    p = _cache_path(cache.ticker)
    p.write_text(json.dumps(asdict(cache), indent=2), encoding="utf-8")
    return p


def invalidate_cache(ticker: str) -> bool:
    p = _cache_path(ticker)
    if p.exists():
        p.unlink()
        return True
    return False


# ────────────────────────────────────────────────────────────────────────────
# Cache invalidation triggers
# ────────────────────────────────────────────────────────────────────────────


def cache_status(
    ticker: str,
    clients: Optional[FinanceClients] = None,
) -> dict:
    """Resolve the cache state for a ticker, applying invalidation rules.

    Returns: {
      status: STATUS_*,
      generated_at: iso | None,
      ttl_until: iso | None,
      stale_reason: str | None,
    }
    """
    cached_blob = load_cached_deepdive(ticker)
    if cached_blob is None:
        return {"status": STATUS_NOT_FOUND, "generated_at": None, "ttl_until": None, "stale_reason": None}

    if cached_blob.error and not cached_blob.markdown:
        return {
            "status": STATUS_FAILED,
            "generated_at": cached_blob.generated_at,
            "ttl_until": cached_blob.ttl_until,
            "stale_reason": cached_blob.error,
        }

    # TTL check
    if not cached_blob.is_fresh():
        return {
            "status": STATUS_STALE,
            "generated_at": cached_blob.generated_at,
            "ttl_until": cached_blob.ttl_until,
            "stale_reason": "TTL expired",
        }

    # Event-based invalidation
    clients = clients or FinanceClients.default()
    snapshot = cached_blob.snapshot or {}

    # Earnings date crossed?
    snapshot_earnings = snapshot.get("next_earnings")
    if snapshot_earnings:
        try:
            er_date = date.fromisoformat(snapshot_earnings)
            if er_date <= date.today():
                return {
                    "status": STATUS_STALE,
                    "generated_at": cached_blob.generated_at,
                    "ttl_until": cached_blob.ttl_until,
                    "stale_reason": f"earnings released ({er_date.isoformat()})",
                }
        except ValueError:
            pass

    # New 8-K filed since cache?
    if not cached_blob.is_crypto:
        try:
            latest_8k = _latest_8k_date(clients, ticker)
        except DataSourceError:
            latest_8k = None
        snapshot_8k = snapshot.get("latest_8k_date")
        if latest_8k and snapshot_8k and latest_8k > snapshot_8k:
            return {
                "status": STATUS_STALE,
                "generated_at": cached_blob.generated_at,
                "ttl_until": cached_blob.ttl_until,
                "stale_reason": f"new 8-K filed {latest_8k}",
            }

    # >5% move from cache snapshot?
    snapshot_close = snapshot.get("close")
    if snapshot_close and clients.polygon.configured:
        try:
            move = clients.polygon.yesterday_change(ticker)
            if move and snapshot_close:
                pct = abs((move["close"] - snapshot_close) / snapshot_close * 100)
                if pct >= INVALIDATE_PRICE_MOVE_PCT:
                    return {
                        "status": STATUS_STALE,
                        "generated_at": cached_blob.generated_at,
                        "ttl_until": cached_blob.ttl_until,
                        "stale_reason": f"price moved {pct:.1f}% since cache",
                    }
        except DataSourceError:
            pass

    return {
        "status": STATUS_FRESH,
        "generated_at": cached_blob.generated_at,
        "ttl_until": cached_blob.ttl_until,
        "stale_reason": None,
    }


def _latest_8k_date(clients: FinanceClients, ticker: str) -> Optional[str]:
    """Latest 8-K filing date as ISO string, or None if none found."""
    try:
        filings = clients.edgar.filings_full(ticker, form_types=("8-K",), days_back=30)
    except DataSourceError:
        return None
    return filings[0]["filing_date"] if filings else None


# ────────────────────────────────────────────────────────────────────────────
# Data gathering — pulls everything the deep-dive prompt needs
# ────────────────────────────────────────────────────────────────────────────


@dataclass
class GatheredData:
    """Bundle of everything we hand to the agent prompt."""
    ticker: str
    is_crypto: bool
    profile: dict = field(default_factory=dict)
    quote: dict = field(default_factory=dict)
    fundamentals: dict = field(default_factory=dict)  # TTM
    history: list[dict] = field(default_factory=list)  # 10y annual
    income_history: list[dict] = field(default_factory=list)
    peers: list[str] = field(default_factory=list)
    peer_metrics: list[dict] = field(default_factory=list)
    earnings_history: list[dict] = field(default_factory=list)
    next_earnings: Optional[str] = None
    transcript: dict = field(default_factory=dict)
    transcript_available: bool = False
    filings: list[dict] = field(default_factory=list)
    insider_trades: list[dict] = field(default_factory=list)
    institutional_holders: list[dict] = field(default_factory=list)
    analyst_estimates: dict = field(default_factory=dict)
    upgrades_downgrades: list[dict] = field(default_factory=list)
    segment_breakdown: dict = field(default_factory=dict)
    macro_series: dict = field(default_factory=dict)
    price_history: list[dict] = field(default_factory=list)
    price_returns: dict = field(default_factory=dict)  # 1mo/3mo/6mo/ytd/1yr
    # Crypto-only
    crypto_market: dict = field(default_factory=dict)
    onchain_available: bool = False
    skipped: list[str] = field(default_factory=list)


def gather_data(
    ticker: str,
    clients: Optional[FinanceClients] = None,
) -> GatheredData:
    """Pull everything the deep-dive prompt needs in one shot.

    Each call is wrapped in try/except DataSourceError so a missing key for
    one source doesn't abort the rest. Skipped sections are collected in
    `data.skipped` for the agent to honestly cite.
    """
    sym = ticker.upper()
    clients = clients or FinanceClients.default()
    is_crypto = sym in _CRYPTO_SYMBOLS

    data = GatheredData(ticker=sym, is_crypto=is_crypto)

    if is_crypto:
        # Crypto path — minimal data on free tier
        try:
            data.crypto_market = clients.coingecko.market(sym)
        except DataSourceError as e:
            data.skipped.append(f"CoinGecko market data — {e.reason}")
        # On-chain connector not configured today (Glassnode/CryptoQuant
        # would need their own clients in finance_data.py).
        data.onchain_available = False
        if not data.onchain_available:
            data.skipped.append(
                "On-chain metrics (NVT/MVRV/exchange-flow) — no Glassnode or "
                "CryptoQuant connector configured. Sections 2/3/5 will be skipped."
            )
        # Macro series for crypto correlation
        if clients.fred.configured:
            try:
                data.macro_series = clients.fred.macro_snapshot()
            except DataSourceError as e:
                data.skipped.append(f"FRED macro — {e.reason}")
        else:
            data.skipped.append("Macro context — set FRED_API_KEY")
        return data

    # ── Equity path ──────────────────────────────────────────────────────

    if clients.fmp.configured:
        try:
            data.profile = clients.fmp.company_profile(sym)
        except DataSourceError as e:
            data.skipped.append(f"Company profile — {e.reason}")
        try:
            data.quote = clients.fmp.quote(sym)
        except DataSourceError as e:
            data.skipped.append(f"Quote — {e.reason}")
        try:
            data.fundamentals = clients.fmp.key_metrics_ttm(sym)
        except DataSourceError as e:
            data.skipped.append(f"TTM fundamentals — {e.reason}")
        try:
            data.history = clients.fmp.key_metrics_history(sym, years=10)
        except DataSourceError as e:
            data.skipped.append(f"10y key metrics history — {e.reason}")
        try:
            data.income_history = clients.fmp.income_statement_history(sym, years=5)
        except DataSourceError as e:
            data.skipped.append(f"Income statement history — {e.reason}")
        try:
            data.peers = clients.fmp.peers(sym)
        except DataSourceError as e:
            data.skipped.append(f"Peer list — {e.reason}")
        # Peer metrics — fetch each peer's TTM
        for peer in data.peers[:5]:
            try:
                peer_q = clients.fmp.quote(peer)
                peer_ttm = clients.fmp.key_metrics_ttm(peer)
                data.peer_metrics.append({
                    "ticker": peer,
                    "price": peer_q.get("price"),
                    "market_cap": peer_q.get("marketCap"),
                    "pe": peer_q.get("pe"),
                    "ev_ebitda": peer_ttm.get("enterpriseValueOverEBITDATTM") or peer_ttm.get("evToEBITDA"),
                    "ps": peer_ttm.get("priceToSalesRatioTTM") or peer_ttm.get("priceToSalesRatio"),
                })
            except DataSourceError:
                continue
        try:
            data.earnings_history = clients.fmp.earnings_history(sym, quarters=4)
        except DataSourceError as e:
            data.skipped.append(f"Earnings history — {e.reason}")
        try:
            ed = clients.fmp.earnings_calendar(sym)
            data.next_earnings = ed.isoformat() if ed else None
        except DataSourceError:
            data.next_earnings = None
        try:
            data.transcript = clients.fmp.transcript(sym)
            data.transcript_available = bool(data.transcript)
        except DataSourceError as e:
            data.skipped.append(f"Earnings transcript — {e.reason} (FMP $30+/mo plan required)")
        try:
            data.insider_trades = clients.fmp.insider_trades(sym, days_back=180)
        except DataSourceError as e:
            data.skipped.append(f"Insider trades (FMP) — {e.reason}")
        try:
            data.institutional_holders = clients.fmp.institutional_holders(sym, top_n=10)
        except DataSourceError as e:
            data.skipped.append(f"13F institutional holders — {e.reason}")
        try:
            data.analyst_estimates = clients.fmp.analyst_estimates(sym)
        except DataSourceError as e:
            data.skipped.append(f"Analyst estimates — {e.reason}")
        try:
            data.upgrades_downgrades = clients.fmp.upgrades_downgrades(sym, limit=20)
        except DataSourceError as e:
            data.skipped.append(f"Upgrades/downgrades — {e.reason}")
        try:
            data.segment_breakdown = clients.fmp.segment_breakdown(sym)
        except DataSourceError as e:
            data.skipped.append(f"Segment breakdown — {e.reason}")
    else:
        data.skipped.append(
            "FMP not configured — sections 2 (valuation), 4 (earnings), 6 (analyst/13F), "
            "and most of 7 (peer table) are skipped. Set FMP_API_KEY in apps/api/.env."
        )

    # EDGAR (always free) — last-180-day filings + Form 4 fallback
    try:
        data.filings = clients.edgar.filings_full(
            sym, form_types=("10-K", "10-Q", "8-K", "DEF 14A"), days_back=180,
        )
    except DataSourceError as e:
        data.skipped.append(f"EDGAR filings — {e.reason}")
    if not data.insider_trades:
        try:
            data.insider_trades = clients.edgar.form4_activity(sym, days_back=180)
        except DataSourceError:
            pass

    # Polygon — price history + 1mo/3mo/6mo/ytd/1yr returns
    if clients.polygon.configured:
        try:
            bars = clients.polygon.daily_aggregates(sym, days=260)  # ~1yr
            data.price_history = bars
            data.price_returns = _compute_returns(bars)
        except DataSourceError as e:
            data.skipped.append(f"Price history — {e.reason}")
    else:
        data.skipped.append("Price history & momentum — set POLYGON_API_KEY")

    # FRED — sector-relevant macro series
    if clients.fred.configured:
        sector = data.profile.get("sector", "") if data.profile else ""
        for series_id in macro_drivers_for(sector):
            try:
                d, v = clients.fred.latest(series_id)
                data.macro_series[series_id] = {"date": d.isoformat(), "value": v}
            except DataSourceError:
                continue
    else:
        data.skipped.append("Macro context — set FRED_API_KEY")

    return data


def _compute_returns(bars: list[dict]) -> dict:
    """Compute 1mo/3mo/6mo/ytd/1yr returns from desc-sorted Polygon daily bars."""
    if len(bars) < 2:
        return {}
    latest_close = bars[0].get("c")
    if not latest_close:
        return {}
    out: dict[str, float] = {}
    targets = {"1mo": 21, "3mo": 63, "6mo": 126, "1yr": 252}
    for label, days_back in targets.items():
        if len(bars) > days_back:
            ref = bars[days_back].get("c")
            if ref:
                out[label] = round((latest_close / ref - 1) * 100, 2)
    # YTD — find first bar of current year
    today = date.today()
    for b in reversed(bars):
        try:
            bd = datetime.fromtimestamp(b["t"] / 1000).date()
            if bd.year == today.year:
                out["ytd"] = round((latest_close / b["c"] - 1) * 100, 2)
                break
        except (KeyError, ValueError, ZeroDivisionError):
            continue
    return out


# ────────────────────────────────────────────────────────────────────────────
# Prompt builder
# ────────────────────────────────────────────────────────────────────────────


def _render_data_for_prompt(data: GatheredData) -> str:
    """Compact markdown rendering of GatheredData for the agent's input."""
    lines: list[str] = []
    sym = data.ticker
    lines.append(f"# Deep-dive inputs — {sym}")
    lines.append(f"Type: {'crypto' if data.is_crypto else 'equity'}")
    lines.append(f"Generated at: {datetime.now().isoformat(timespec='seconds')}")
    lines.append("")

    if data.skipped:
        lines.append("## Sections / data unavailable")
        for s in data.skipped:
            lines.append(f"- {s}")
        lines.append("")

    if data.profile:
        p = data.profile
        lines.append("## Company profile")
        lines.append(f"- Name: {p.get('companyName')}")
        lines.append(f"- Sector: {p.get('sector')} / Industry: {p.get('industry')}")
        lines.append(f"- Market cap: ${p.get('mktCap', 0):,}")
        lines.append(f"- Employees: {p.get('fullTimeEmployees')}")
        lines.append(f"- Description: {(p.get('description') or '')[:600]}")
        lines.append(f"- Website: {p.get('website')}")
        lines.append("")

    if data.quote:
        q = data.quote
        lines.append("## Quote")
        lines.append(f"- Price: ${q.get('price')}  Change: {q.get('changesPercentage')}%")
        lines.append(f"- 52w high/low: ${q.get('yearHigh')} / ${q.get('yearLow')}")
        lines.append(f"- Avg volume: {q.get('avgVolume')}")
        lines.append("")

    if data.fundamentals:
        f = data.fundamentals
        lines.append("## TTM fundamentals")
        for k in [
            "peRatioTTM","priceToSalesRatioTTM","priceToBookRatioTTM",
            "evToEBITDA","enterpriseValueOverEBITDATTM",
            "freeCashFlowYieldTTM","returnOnEquityTTM","returnOnInvestedCapitalTTM",
            "debtToEquityTTM","grossProfitMarginTTM","operatingProfitMarginTTM",
        ]:
            if f.get(k) is not None:
                lines.append(f"- {k}: {f[k]}")
        lines.append("")

    if data.history:
        lines.append("## 10y annual key metrics (most recent first)")
        for h in data.history[:10]:
            yr = h.get("calendarYear") or h.get("date", "")[:4]
            lines.append(
                f"- {yr}: P/E={h.get('peRatio')}, EV/EBITDA={h.get('enterpriseValueOverEBITDA')}, "
                f"P/S={h.get('priceToSalesRatio')}"
            )
        lines.append("")

    if data.income_history:
        lines.append("## 5y income statement (revenue, GP%, OP%, EPS)")
        for inc in data.income_history[:5]:
            yr = inc.get("calendarYear") or inc.get("date", "")[:4]
            rev = inc.get("revenue", 0)
            gp = inc.get("grossProfitRatio")
            op = inc.get("operatingIncomeRatio")
            eps = inc.get("eps")
            lines.append(f"- {yr}: revenue=${rev:,}, GP%={gp}, OP%={op}, EPS=${eps}")
        lines.append("")

    if data.earnings_history:
        lines.append("## Last 4 quarters — actual vs estimate")
        for e in data.earnings_history:
            lines.append(
                f"- {e.get('date')}: actual EPS ${e.get('actualEarningResult')} "
                f"vs estimate ${e.get('estimatedEarning')} "
                f"({e.get('symbol')})"
            )
        lines.append("")

    if data.next_earnings:
        lines.append(f"## Next earnings: {data.next_earnings}")
        lines.append("")

    if data.peer_metrics:
        lines.append("## Peer table")
        lines.append("| Ticker | Price | Mcap | P/E | EV/EBITDA | P/S |")
        lines.append("|---|---|---|---|---|---|")
        for p in data.peer_metrics:
            mc = p.get("market_cap") or 0
            mc_b = f"${mc/1e9:.1f}B" if mc else "—"
            lines.append(
                f"| {p['ticker']} | ${p.get('price')} | {mc_b} | {p.get('pe')} | "
                f"{p.get('ev_ebitda')} | {p.get('ps')} |"
            )
        lines.append("")

    if data.transcript_available and data.transcript:
        lines.append("## Most recent earnings transcript (truncated)")
        # Truncate the raw transcript to keep token cost reasonable.
        content = (data.transcript.get("content") or "")[:3500]
        lines.append(content)
        lines.append("")
    else:
        lines.append("## Earnings transcript")
        lines.append("- Not available on free FMP tier. The agent should note "
                     "this in section 5 and pull narrative from 8-K filings instead.")
        lines.append("")

    if data.filings:
        lines.append("## Recent SEC filings (last 180 days)")
        for f in data.filings[:15]:
            lines.append(f"- {f['form']}  {f['filing_date']}  {f['primary_doc_url']}")
        lines.append("")

    if data.insider_trades:
        lines.append("## Insider trades (Form 4) — last 180 days")
        for t in data.insider_trades[:10]:
            # Mix of FMP + EDGAR shapes
            who = t.get("reportingName") or t.get("name") or t.get("filer") or "?"
            ttype = t.get("transactionType") or t.get("form") or "?"
            shares = t.get("securitiesTransacted") or t.get("transactionShares") or "?"
            d_field = t.get("transactionDate") or t.get("filing_date") or "?"
            lines.append(f"- {d_field}: {who} — {ttype} — {shares} shares")
        lines.append("")

    if data.institutional_holders:
        lines.append("## Top 10 institutional holders")
        for h in data.institutional_holders[:10]:
            lines.append(
                f"- {h.get('holder')}: {h.get('shares', 0):,} shares "
                f"(${h.get('marketValue', 0):,} market value)"
            )
        lines.append("")

    if data.analyst_estimates:
        e = data.analyst_estimates
        lines.append("## Analyst consensus")
        lines.append(
            f"- Recommendation distribution: strongBuy={e.get('strongBuy')}, "
            f"buy={e.get('buy')}, hold={e.get('hold')}, sell={e.get('sell')}, "
            f"strongSell={e.get('strongSell')} (consensus: {e.get('consensus_recommendation')})"
        )
        lines.append("")

    if data.upgrades_downgrades:
        lines.append("## Recent sell-side actions")
        for u in data.upgrades_downgrades[:8]:
            lines.append(
                f"- {u.get('publishedDate', '')[:10]}: {u.get('analystCompany')} — "
                f"{u.get('previousGrade')} → {u.get('newGrade')} "
                f"(target: {u.get('priceTarget')})"
            )
        lines.append("")

    if data.segment_breakdown:
        lines.append("## Revenue segmentation")
        seg = data.segment_breakdown.get("segments") or {}
        reg = data.segment_breakdown.get("regions") or {}
        if seg:
            lines.append("- By segment:")
            for k, v in list(seg.items())[:10]:
                lines.append(f"  - {k}: ${v:,}" if isinstance(v, (int, float)) else f"  - {k}: {v}")
        if reg:
            lines.append("- By region:")
            for k, v in list(reg.items())[:10]:
                lines.append(f"  - {k}: ${v:,}" if isinstance(v, (int, float)) else f"  - {k}: {v}")
        lines.append("")

    if data.price_returns:
        lines.append("## Price returns")
        for label, pct in data.price_returns.items():
            lines.append(f"- {label}: {pct:+.2f}%")
        lines.append("")

    if data.macro_series:
        lines.append("## Sector-relevant macro (latest values)")
        for series_id, payload in data.macro_series.items():
            if isinstance(payload, dict) and "value" in payload:
                lines.append(f"- {series_id}: {payload['value']} (as of {payload['date']})")
        lines.append("")

    if data.is_crypto and data.crypto_market:
        lines.append("## Crypto market data")
        m = data.crypto_market
        lines.append(f"- Price: ${m.get('current_price'):,}")
        lines.append(f"- Market cap: ${m.get('market_cap'):,}")
        lines.append(f"- 24h change: {m.get('price_change_percentage_24h')}%")
        lines.append(f"- ATH: ${m.get('ath'):,} ({m.get('ath_date', '')[:10]})")
        lines.append("")

    return "\n".join(lines)


def _build_prompt(data: GatheredData) -> str:
    """Wrap the gathered data with the agent's instructions for deep-dive mode."""
    format_spec = (
        "DEEPDIVE_FORMAT_CRYPTO.md" if data.is_crypto else "DEEPDIVE_FORMAT.md"
    )
    rendered = _render_data_for_prompt(data)
    return f"""Deep-dive mode. Write a comprehensive single-ticker analysis for
{data.ticker} following ~/.borina/agents/finance/{format_spec} EXACTLY.

You have access to WebFetch. Use it to fill the gaps when our pre-gathered
inputs below are sparse — pull from public sources only:
  - SEC EDGAR filings (https://www.sec.gov/) — gold standard for filings
  - Yahoo Finance (https://finance.yahoo.com/quote/{data.ticker}/) — quotes,
    multiples, key statistics, peer comps
  - Stock Analysis (https://stockanalysis.com/stocks/{data.ticker.lower()}/)
    — clean financial-statement history, ratios
  - Investor relations site for the issuer (linked in profile if present)
  - For crypto: CoinGecko, the protocol's own docs, blockchain explorers

Citation discipline is non-negotiable:
- Every claim cites a specific source URL
- Every multiple shows the input numbers (revenue, market cap, etc.)
- Every quote names the speaker and timestamp/page
- Don't paraphrase a filing you haven't fetched
- Don't invent peer multiples without retrieving them

If WebFetch can't reach a source (rate-limited, 404), say so and continue.
The "What I couldn't analyze" section (#10) stays non-negotiable — list any
section where you fell back, why, and what would unlock it.

Per-dimension scoring (Bull / Bear / Neutral) only — never an overall verdict.
For dimensions you successfully fill via web research, score them; for
dimensions still missing data, use "N/A — insufficient data".

Output pure markdown. Start with the H1 from the format spec. End with the
"Generated in Xs. Cached until Y." footer. Do not wrap in code fences.

────────────────── DEEP-DIVE INPUTS (pre-gathered) ──────────────────

{rendered}

────────────────── END OF PRE-GATHERED INPUTS ──────────────────

Now write the deep-dive. Lead with the multiples + price + recent filings —
those are the highest-value sections. Use WebFetch for anything missing.
"""


# ────────────────────────────────────────────────────────────────────────────
# Generation orchestrator
# ────────────────────────────────────────────────────────────────────────────


async def _set_status(ticker: str, status: str, **extra) -> None:
    async with _active_runs_lock:
        run = _active_runs.setdefault(ticker, {"status": status, "events": []})
        run["status"] = status
        run.update(extra)
        run["events"].append({
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "status": status,
            **extra,
        })


def get_run_state(ticker: str) -> Optional[dict]:
    """Snapshot of an in-flight generation, if any."""
    return _active_runs.get(ticker.upper())


async def generate_deepdive(
    ticker: str,
    *,
    clients: Optional[FinanceClients] = None,
    use_cache: bool = True,
) -> DeepDiveCache:
    """Run the full deep-dive flow.

    1. Check cache (unless ``use_cache=False``)
    2. Gather data — emits "gathering" SSE event
    3. Build prompt + dispatch to the agent — emits "running_agent"
    4. Cache + return — emits "complete"
    """
    sym = ticker.upper()

    if use_cache:
        existing = cache_status(sym, clients=clients)
        if existing["status"] == STATUS_FRESH:
            cached_blob = load_cached_deepdive(sym)
            if cached_blob:
                return cached_blob

    started = time.time()
    await _set_status(sym, STATUS_GENERATING, phase="gathering")

    clients = clients or FinanceClients.default()
    data = gather_data(sym, clients=clients)

    await _set_status(sym, STATUS_GENERATING, phase="running_agent")
    prompt = _build_prompt(data)

    try:
        from agents.runner_v2 import run_agent_task
        result = await run_agent_task(
            "finance",
            prompt,
            timeout_seconds=1800,  # 30 min — comprehensive deep-dive can be long
            idle_seconds=8,
        )
        markdown = _clean_brief_output(result.output) if result.ok else ""
        error = None if result.ok else (result.error or "unknown error")
    except Exception as e:
        markdown = ""
        error = f"{type(e).__name__}: {e!r}"

    duration = round(time.time() - started, 2)
    now = datetime.now(timezone.utc)
    ttl_until = (now + timedelta(hours=CACHE_TTL_HOURS)).isoformat(timespec="seconds")

    snapshot = {
        "close": data.quote.get("price") if data.quote else None,
        "next_earnings": data.next_earnings,
        "latest_8k_date": next(
            (f["filing_date"] for f in data.filings if f["form"] == "8-K"),
            None,
        ),
    }

    cache = DeepDiveCache(
        ticker=sym,
        is_crypto=data.is_crypto,
        generated_at=now.isoformat(timespec="seconds"),
        ttl_until=ttl_until,
        duration_seconds=duration,
        markdown=markdown,
        error=error,
        snapshot=snapshot,
        data_source_status=clients.configured_summary(),
    )
    save_cached_deepdive(cache)

    await _set_status(
        sym,
        STATUS_FRESH if not error else STATUS_FAILED,
        phase="complete",
        duration_seconds=duration,
    )
    return cache


def split_into_sections(markdown: str) -> list[dict]:
    """Split a deep-dive markdown into [{anchor, title, body}] for nav use.

    Anchors on H2 headings ("## 1. …", "## 2. …" etc.). The scorecard table
    above section 1 lives under a synthetic "Scorecard" anchor.
    """
    lines = markdown.split("\n")
    sections: list[dict] = []
    cur_title: Optional[str] = None
    cur_body: list[str] = []
    h2_re = re.compile(r"^##\s+(.+)$")
    for ln in lines:
        m = h2_re.match(ln)
        if m:
            if cur_title is not None:
                sections.append({
                    "anchor": _slug(cur_title),
                    "title": cur_title,
                    "body": "\n".join(cur_body).strip(),
                })
            cur_title = m.group(1).strip()
            cur_body = []
        else:
            if cur_title is None:
                # Pre-section header / scorecard → bucket into "Scorecard"
                cur_title = "Scorecard"
                cur_body = []
            cur_body.append(ln)
    if cur_title is not None:
        sections.append({
            "anchor": _slug(cur_title),
            "title": cur_title,
            "body": "\n".join(cur_body).strip(),
        })
    return sections


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
