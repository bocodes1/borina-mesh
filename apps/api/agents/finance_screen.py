"""Finance screen — produces structured input for the agent's brief.

The agent doesn't run the screen itself; this module does it deterministically
in Python so the agent's job is purely "write up these candidates in the brief
format". That keeps the LLM out of the data-gathering loop where it would
hallucinate numbers.

Inputs: FinanceClients (5 sources)
Outputs: ScreenResult — what the agent prompt is templated from
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from typing import Optional

from agents.finance_data import (
    DataSourceError,
    FinanceClients,
    load_watchlist,
)


# ────────────────────────────────────────────────────────────────────────────
# Data shapes
# ────────────────────────────────────────────────────────────────────────────


@dataclass
class WatchlistMove:
    """A watchlist ticker that moved >threshold yesterday."""
    ticker: str
    change_pct: float
    volume_ratio: float
    close: float
    as_of: str
    earnings_in_days: Optional[int] = None  # None = no upcoming earnings or unknown
    excluded_reason: Optional[str] = None  # e.g. "earnings tomorrow"


@dataclass
class ValuationSnapshot:
    """All three lenses for one equity candidate."""
    ticker: str
    name: str = ""
    sector: str = ""

    # Quote
    price: Optional[float] = None
    market_cap: Optional[float] = None

    # Lens 1: vs own history
    forward_pe: Optional[float] = None
    pe_5y_median: Optional[float] = None
    pe_10y_median: Optional[float] = None
    ev_ebitda: Optional[float] = None
    ev_ebitda_5y_median: Optional[float] = None
    ps: Optional[float] = None
    ps_5y_median: Optional[float] = None
    history_warning: Optional[str] = None  # "P/E ranged 8-60x — may not be comparable"

    # Lens 2: vs peers
    peers: list[str] = field(default_factory=list)
    peer_pe_median: Optional[float] = None
    peer_ev_ebitda_median: Optional[float] = None
    peer_ps_median: Optional[float] = None

    # Lens 3: DCF implied growth
    implied_dcf_growth_pct: Optional[float] = None
    actual_3y_revenue_cagr_pct: Optional[float] = None

    # Earnings filter status
    earnings_in_days: Optional[int] = None

    # Recent filings + ownership
    recent_filings: list[dict] = field(default_factory=list)
    institutional_changes: list[dict] = field(default_factory=list)


@dataclass
class CryptoSnapshot:
    """On-chain / market snapshot for a crypto candidate."""
    symbol: str
    name: str
    price: Optional[float] = None
    market_cap: Optional[float] = None
    change_24h_pct: Optional[float] = None
    # Stub fields for future on-chain data (NVT, MVRV, exchange flows).
    # Filled in when a Glassnode/Coinmetrics connector is wired up.
    nvt_ratio: Optional[float] = None
    mvrv: Optional[float] = None
    exchange_net_flow_7d: Optional[float] = None


@dataclass
class ScreenResult:
    """Everything the agent needs to write the morning brief."""
    generated_at: str
    trading_date: str
    watchlist_movement: list[WatchlistMove] = field(default_factory=list)
    candidates_equity: list[ValuationSnapshot] = field(default_factory=list)
    candidates_crypto: list[CryptoSnapshot] = field(default_factory=list)
    pipeline: list[dict] = field(default_factory=list)
    macro: dict = field(default_factory=dict)
    filter_stats: dict[str, int] = field(default_factory=dict)
    skipped_sections: list[str] = field(default_factory=list)
    data_source_status: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


# ────────────────────────────────────────────────────────────────────────────
# Lens helpers
# ────────────────────────────────────────────────────────────────────────────


def _median(xs: list[float]) -> Optional[float]:
    xs = [x for x in xs if isinstance(x, (int, float)) and x is not None]
    if not xs:
        return None
    return float(statistics.median(xs))


def _pe_history(history: list[dict]) -> tuple[Optional[float], Optional[float], Optional[str]]:
    """Compute 5-year and 10-year median P/E from FMP key-metrics history.

    Returns (median_5y, median_10y, warning_or_None). Warning fires when the
    range is suspiciously wide — often a sign of structural change (M&A,
    accounting restatement) where the median is misleading.
    """
    pe_values = [m.get("peRatio") for m in history if m.get("peRatio") not in (None, 0)]
    pe_values = [float(v) for v in pe_values if v]
    if not pe_values:
        return None, None, None
    five_year = _median(pe_values[:5])
    ten_year = _median(pe_values[:10])
    warning = None
    if pe_values:
        lo, hi = min(pe_values), max(pe_values)
        if lo > 0 and hi / lo > 5:  # P/E swung >5x — flag for the agent
            warning = (
                f"P/E ranged {lo:.0f}x to {hi:.0f}x over the period — may not be "
                f"comparable across years (possible M&A, divestiture, or large "
                f"swing year). Investigate before relying on the median."
            )
    return five_year, ten_year, warning


def _ev_ebitda_history(history: list[dict]) -> Optional[float]:
    vals = [m.get("enterpriseValueOverEBITDA") for m in history if m.get("enterpriseValueOverEBITDA")]
    return _median([float(v) for v in vals[:5]])


def _ps_history(history: list[dict]) -> Optional[float]:
    vals = [m.get("priceToSalesRatio") for m in history if m.get("priceToSalesRatio")]
    return _median([float(v) for v in vals[:5]])


def _implied_dcf_growth(history: list[dict], current_pe: Optional[float]) -> Optional[float]:
    """Cheap DCF sanity check: at current P/E, what perpetual growth rate is
    implied by a Gordon-growth approximation (P/E ≈ 1 / (r - g))?

    Solve: g = r - 1/PE. Use r = 9% as a stock-picker's discount rate.
    Result is annualised; clamps below -5% to None to avoid degenerate values.
    """
    if not current_pe or current_pe <= 0:
        return None
    r = 0.09
    g = r - 1 / current_pe
    if g < -0.05:
        return None
    return round(g * 100, 1)


def _actual_3y_revenue_cagr(income_history: list[dict]) -> Optional[float]:
    """Annualised revenue CAGR over the last 3 fiscal years, or None."""
    revs = [s.get("revenue") for s in income_history if s.get("revenue")]
    revs = [float(v) for v in revs if v]
    if len(revs) < 4:
        return None
    end, start = revs[0], revs[3]
    if start <= 0:
        return None
    cagr = (end / start) ** (1 / 3) - 1
    return round(cagr * 100, 1)


# ────────────────────────────────────────────────────────────────────────────
# Section builders
# ────────────────────────────────────────────────────────────────────────────


def _watchlist_movement(
    clients: FinanceClients,
    tickers: list[str],
    move_threshold_pct: float = 2.0,
    earnings_skip_days: int = 5,
) -> tuple[list[WatchlistMove], int]:
    """Yesterday's >threshold movers from the watchlist.

    Returns (moves, excluded_for_earnings_count). Tickers within
    ``earnings_skip_days`` of an earnings release are excluded from the
    movement section because the move is not actionable signal.
    """
    if not clients.polygon.configured:
        return [], 0

    out: list[WatchlistMove] = []
    excluded = 0
    for ticker in tickers:
        try:
            change = clients.polygon.yesterday_change(ticker)
        except DataSourceError:
            continue
        if change is None:
            continue
        if abs(change["change_pct"]) < move_threshold_pct:
            continue

        days_to_er: Optional[int] = None
        excluded_reason: Optional[str] = None
        if clients.fmp.configured:
            try:
                days_to_er = clients.fmp.days_to_earnings(ticker)
            except DataSourceError:
                pass
            if days_to_er is not None and 0 <= days_to_er <= earnings_skip_days:
                excluded_reason = f"earnings in {days_to_er}d — move likely positioning, not info"
                excluded += 1

        out.append(WatchlistMove(
            ticker=ticker,
            change_pct=change["change_pct"],
            volume_ratio=change["volume_ratio"],
            close=change["close"],
            as_of=change["as_of"],
            earnings_in_days=days_to_er,
            excluded_reason=excluded_reason,
        ))
    return out, excluded


def _equity_candidate(
    clients: FinanceClients,
    ticker: str,
    earnings_skip_days: int = 5,
) -> Optional[ValuationSnapshot]:
    """Compute all three valuation lenses for one ticker.

    Returns None if the ticker should be excluded (earnings too soon, missing
    data, or filter rejection). Returns a partial ValuationSnapshot with
    None-valued lenses if some computations failed but the candidate is
    otherwise valid.
    """
    if not clients.fmp.configured:
        return None

    try:
        quote = clients.fmp.quote(ticker)
    except DataSourceError:
        return None

    market_cap = quote.get("marketCap")
    if market_cap is not None and market_cap < 500_000_000:
        return None

    snap = ValuationSnapshot(
        ticker=ticker,
        name=quote.get("name", ""),
        price=quote.get("price"),
        market_cap=market_cap,
        forward_pe=quote.get("pe"),
    )

    # Earnings filter — kill candidate if too close to earnings.
    try:
        snap.earnings_in_days = clients.fmp.days_to_earnings(ticker)
    except DataSourceError:
        snap.earnings_in_days = None
    if snap.earnings_in_days is not None and 0 <= snap.earnings_in_days <= earnings_skip_days:
        return None

    # Lens 1: vs own history
    try:
        history = clients.fmp.key_metrics_history(ticker, years=10)
        snap.pe_5y_median, snap.pe_10y_median, snap.history_warning = _pe_history(history)
        snap.ev_ebitda_5y_median = _ev_ebitda_history(history)
        snap.ps_5y_median = _ps_history(history)
    except DataSourceError:
        pass

    try:
        ttm = clients.fmp.key_metrics_ttm(ticker)
        snap.ev_ebitda = ttm.get("enterpriseValueOverEBITDATTM") or ttm.get("evToEBITDA")
        snap.ps = ttm.get("priceToSalesRatioTTM") or ttm.get("priceToSalesRatio")
    except DataSourceError:
        pass

    # Lens 2: vs peers
    try:
        snap.peers = clients.fmp.peers(ticker)
        peer_pes: list[float] = []
        peer_ev_ebs: list[float] = []
        peer_pss: list[float] = []
        for peer in snap.peers[:5]:
            try:
                pq = clients.fmp.quote(peer)
                if pq.get("pe"):
                    peer_pes.append(float(pq["pe"]))
                ptm = clients.fmp.key_metrics_ttm(peer)
                ev = ptm.get("enterpriseValueOverEBITDATTM") or ptm.get("evToEBITDA")
                ps = ptm.get("priceToSalesRatioTTM") or ptm.get("priceToSalesRatio")
                if ev:
                    peer_ev_ebs.append(float(ev))
                if ps:
                    peer_pss.append(float(ps))
            except DataSourceError:
                continue
        snap.peer_pe_median = _median(peer_pes)
        snap.peer_ev_ebitda_median = _median(peer_ev_ebs)
        snap.peer_ps_median = _median(peer_pss)
    except DataSourceError:
        pass

    # Lens 3: DCF implied growth + 3y actual
    snap.implied_dcf_growth_pct = _implied_dcf_growth(history if 'history' in locals() else [], snap.forward_pe)
    try:
        income = clients.fmp.income_statement_history(ticker, years=5)
        snap.actual_3y_revenue_cagr_pct = _actual_3y_revenue_cagr(income)
    except DataSourceError:
        pass

    # Recent filings (free, EDGAR)
    try:
        snap.recent_filings = clients.edgar.recent_filings(
            ticker, form_types=("10-K", "10-Q")
        )[:2]
    except DataSourceError:
        pass

    try:
        snap.institutional_changes = clients.fmp.institutional_ownership_change(ticker)
    except DataSourceError:
        pass

    return snap


def _is_undervalued(snap: ValuationSnapshot) -> bool:
    """Cheap heuristic: candidate trades meaningfully below own and peer median.

    Either P/E is at least 15% below own 5y median AND below peer median,
    OR EV/EBITDA is at least 20% below own 5y median AND below peer median.
    Pickier than necessary so the agent gets ≤5 candidates to write up.
    """
    if snap.forward_pe and snap.pe_5y_median and snap.peer_pe_median:
        if (
            snap.forward_pe < 0.85 * snap.pe_5y_median
            and snap.forward_pe < 0.95 * snap.peer_pe_median
        ):
            return True
    if snap.ev_ebitda and snap.ev_ebitda_5y_median and snap.peer_ev_ebitda_median:
        if (
            snap.ev_ebitda < 0.80 * snap.ev_ebitda_5y_median
            and snap.ev_ebitda < 0.95 * snap.peer_ev_ebitda_median
        ):
            return True
    return False


def _crypto_candidates(clients: FinanceClients) -> list[CryptoSnapshot]:
    """Crypto majors with > $5B market cap. On-chain lenses are stubs for now."""
    out: list[CryptoSnapshot] = []
    for entry in clients.coingecko.candidates_over_threshold(5_000_000_000):
        out.append(CryptoSnapshot(
            symbol=entry["symbol"],
            name=entry["name"],
            price=entry.get("price"),
            market_cap=entry.get("market_cap"),
            change_24h_pct=entry.get("change_24h_pct"),
        ))
    return out


# ────────────────────────────────────────────────────────────────────────────
# Top-level screen
# ────────────────────────────────────────────────────────────────────────────


def run_screen(
    clients: Optional[FinanceClients] = None,
    universe: Optional[list[str]] = None,
    move_threshold_pct: float = 2.0,
    max_equity_candidates: int = 3,
) -> ScreenResult:
    """Run the full morning screen.

    Args:
        clients: configured FinanceClients (default: build from env)
        universe: tickers to screen for undervalued candidates. If None, uses
            the watchlist as the universe — small but lets the brief still run
            without a paid universe-list source.
        move_threshold_pct: yesterday's |change| threshold for the watchlist
            movement section.
        max_equity_candidates: cap candidates the agent writes up (≤3 per spec).

    Returns:
        ScreenResult — feed this directly into the agent prompt template.
    """
    if clients is None:
        clients = FinanceClients.default()

    skipped: list[str] = []
    filter_stats = {
        "excluded_earnings_within_5d": 0,
        "excluded_below_500m_mcap": 0,
        "universe_size": 0,
    }
    watchlist = load_watchlist()

    # Macro snapshot
    macro: dict = {}
    if clients.fred.configured:
        macro = clients.fred.macro_snapshot()
    else:
        skipped.append("Macro snapshot — set FRED_API_KEY in .env to enable")

    # Watchlist movement
    if clients.polygon.configured:
        moves, excluded_er = _watchlist_movement(
            clients, watchlist, move_threshold_pct=move_threshold_pct
        )
        filter_stats["excluded_earnings_within_5d"] += excluded_er
    else:
        moves = []
        skipped.append(
            "Watchlist movement — set POLYGON_API_KEY in .env to enable >2% screen"
        )

    # Equity candidates
    candidates_equity: list[ValuationSnapshot] = []
    if clients.fmp.configured:
        candidate_universe = universe or watchlist
        filter_stats["universe_size"] = len(candidate_universe)
        for ticker in candidate_universe:
            snap = _equity_candidate(clients, ticker)
            if snap is None:
                # Either earnings filter, missing data, or below mcap
                continue
            if _is_undervalued(snap):
                candidates_equity.append(snap)
                if len(candidates_equity) >= max_equity_candidates:
                    break
    else:
        skipped.append(
            "Equity candidates — set FMP_API_KEY in .env to enable multiple-based screening"
        )

    # Crypto candidates
    candidates_crypto = _crypto_candidates(clients)

    # Pipeline (watchlist tickers that didn't make the candidates cut)
    pipeline = [
        {"ticker": t, "note": "watching — has not screened as undervalued today"}
        for t in watchlist
        if t not in {c.ticker for c in candidates_equity}
    ]

    return ScreenResult(
        generated_at=datetime.now().isoformat(timespec="seconds"),
        trading_date=date.today().isoformat(),
        watchlist_movement=moves,
        candidates_equity=candidates_equity,
        candidates_crypto=candidates_crypto,
        pipeline=pipeline,
        macro=macro,
        filter_stats=filter_stats,
        skipped_sections=skipped,
        data_source_status=clients.configured_summary(),
    )


def render_screen_for_prompt(screen: ScreenResult) -> str:
    """Render a ScreenResult as a structured markdown block for the agent prompt.

    The agent's job is to *write up* this data in the BRIEF_FORMAT.md voice.
    Don't include analysis here — just the raw inputs the agent needs.
    """
    lines: list[str] = []
    lines.append(f"# Screen results — {screen.trading_date}")
    lines.append(f"Generated at: {screen.generated_at}")
    lines.append("")

    lines.append("## Data sources available")
    for src, ok in screen.data_source_status.items():
        lines.append(f"- {src}: {'configured' if ok else 'NOT configured (skipped)'}")
    lines.append("")

    if screen.skipped_sections:
        lines.append("## Sections skipped today")
        for s in screen.skipped_sections:
            lines.append(f"- {s}")
        lines.append("")

    lines.append("## Macro context")
    if screen.macro:
        for k, v in screen.macro.items():
            if isinstance(v, dict) and "value" in v:
                lines.append(f"- {k}: {v['value']} (as of {v['date']})")
            elif isinstance(v, dict) and "error" in v:
                lines.append(f"- {k}: unavailable ({v['error']})")
    else:
        lines.append("- No macro data available today.")
    lines.append("")

    lines.append("## Watchlist movement (>2% yesterday)")
    if screen.watchlist_movement:
        for m in screen.watchlist_movement:
            excluded = f" [EXCLUDED: {m.excluded_reason}]" if m.excluded_reason else ""
            er = f" earnings_in_{m.earnings_in_days}d" if m.earnings_in_days is not None else ""
            lines.append(
                f"- {m.ticker}: {m.change_pct:+.2f}% on {m.volume_ratio}x avg volume "
                f"(close ${m.close:.2f}, as_of {m.as_of}){er}{excluded}"
            )
    else:
        lines.append("- No watchlist movements above threshold today.")
    lines.append("")

    lines.append(f"## Equity candidates ({len(screen.candidates_equity)})")
    if not screen.candidates_equity:
        lines.append("- 0 candidates passed today's screen. Honestly say so in the brief.")
    for c in screen.candidates_equity:
        lines.append(f"### {c.ticker} — {c.name}")
        lines.append(f"- Price: ${c.price}  Market cap: ${c.market_cap:,.0f}" if c.price and c.market_cap else f"- Price/mcap missing")
        lines.append(f"- Forward P/E: {c.forward_pe}  |  5y median: {c.pe_5y_median}  |  10y median: {c.pe_10y_median}  |  Peer median: {c.peer_pe_median}")
        lines.append(f"- EV/EBITDA: {c.ev_ebitda}  |  5y median: {c.ev_ebitda_5y_median}  |  Peer median: {c.peer_ev_ebitda_median}")
        lines.append(f"- P/S: {c.ps}  |  5y median: {c.ps_5y_median}  |  Peer median: {c.peer_ps_median}")
        lines.append(f"- Implied DCF growth at current price: {c.implied_dcf_growth_pct}%/yr  |  Last 3y revenue CAGR: {c.actual_3y_revenue_cagr_pct}%/yr")
        if c.history_warning:
            lines.append(f"- WARNING: {c.history_warning}")
        if c.peers:
            lines.append(f"- Peers: {', '.join(c.peers)}")
        if c.recent_filings:
            lines.append("- Recent filings:")
            for f in c.recent_filings:
                lines.append(f"  - {f['form']} {f['filing_date']} — {f['primary_doc_url']}")
        if c.institutional_changes:
            lines.append(f"- Institutional ownership snapshot: {c.institutional_changes[0] if c.institutional_changes else 'n/a'}")
        if c.earnings_in_days is not None:
            lines.append(f"- Next earnings in: {c.earnings_in_days} days")
        lines.append("")

    if screen.candidates_crypto:
        lines.append(f"## Crypto candidates ({len(screen.candidates_crypto)})")
        for c in screen.candidates_crypto:
            lines.append(
                f"- {c.symbol} ({c.name}): ${c.price:,.0f}  mcap ${c.market_cap/1e9:.0f}B  "
                f"24h {c.change_24h_pct:+.2f}%"
            )
        lines.append("")

    if screen.pipeline:
        lines.append("## Pipeline")
        for p in screen.pipeline:
            lines.append(f"- {p['ticker']}: {p['note']}")
        lines.append("")

    lines.append("## Filter stats")
    for k, v in screen.filter_stats.items():
        lines.append(f"- {k}: {v}")
    lines.append("")

    return "\n".join(lines)
