"""Polymarket Intel Agent — leaderboard tracking, whale detection, resolution edge analysis."""

from __future__ import annotations

import asyncio
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class Trader:
    address: str
    username: str
    rank: int
    pnl_24h: float
    pnl_7d: float
    pnl_total: float
    volume_24h: float
    win_rate: float
    trades_24h: int
    top_markets: list[str] = field(default_factory=list)
    positions: list[dict] = field(default_factory=list)


@dataclass
class WhaleMove:
    address: str
    market: str
    side: str
    size_usd: float
    price: float
    market_avg_price: float
    is_contrarian: bool


@dataclass
class ResolutionEdge:
    market: str
    rule_text: str
    ambiguity: str
    current_price: float
    estimated_fair: float
    recommendation: str


# ---------------------------------------------------------------------------
# Pure functions (tested)
# ---------------------------------------------------------------------------

AMBIGUITY_SIGNALS = ["may", "could", "unclear", "discretion", "judgment", "interpret"]


def classify_trader(t: Trader) -> str:
    """Classify a trader by their trading pattern."""
    if t.trades_24h >= 100:
        return "HFT Bot"

    # Event Specialist: >50% of top_markets in same category AND >=10 trades
    if t.trades_24h >= 10 and t.top_markets:
        counts = Counter(t.top_markets)
        most_common_count = counts.most_common(1)[0][1]
        if most_common_count / len(t.top_markets) > 0.5:
            return "Event Specialist"

    if t.trades_24h <= 10:
        return "Swing Trader"

    return "Active Trader"


def analyze_strategy_gaps(traders: list[Trader], bot_markets: list[str]) -> list[str]:
    """Find markets top traders are active in that the bot isn't covering."""
    bot_set = set(bot_markets)
    trader_markets: Counter[str] = Counter()
    for t in traders:
        for m in t.top_markets:
            trader_markets[m] += 1

    # Return markets not in bot set, ordered by frequency
    gaps = [m for m, _ in trader_markets.most_common() if m not in bot_set]
    return gaps


def format_report(
    traders: list[Trader],
    whales: list[WhaleMove],
    edges: list[ResolutionEdge],
    strategy_gaps: list[str],
) -> str:
    """Build a full markdown intel report."""
    lines: list[str] = []
    today = date.today().isoformat()

    # Header
    lines.append(f"# Polymarket Intel Report — {today}")
    lines.append("")

    # Leaderboard section
    lines.append("## Leaderboard Movers")
    lines.append("")
    lines.append("| Rank | Trader | PnL 24h | Win Rate | Type |")
    lines.append("|------|--------|---------|----------|------|")
    for t in traders[:20]:
        ttype = classify_trader(t)
        lines.append(
            f"| {t.rank} | {t.username} | ${t.pnl_24h:,.0f} | {t.win_rate:.1f}% | {ttype} |"
        )
    lines.append("")

    # Whale Movements section
    lines.append("## Whale Movements")
    lines.append("")
    for w in whales:
        contra = " (CONTRARIAN)" if w.is_contrarian else ""
        lines.append(
            f"- **{w.address[:8]}…** — {w.side} on *{w.market}* "
            f"${w.size_usd:,.0f} @ {w.price:.2f} (avg {w.market_avg_price:.2f}){contra}"
        )
    lines.append("")

    # Resolution Edge Opportunities section
    lines.append("## Resolution Edge Opportunities")
    lines.append("")
    for e in edges:
        lines.append(f"### {e.market}")
        lines.append(f"- **Rule:** {e.rule_text}")
        lines.append(f"- **Ambiguity:** {e.ambiguity}")
        lines.append(f"- **Price:** {e.current_price:.2f} → est. fair {e.estimated_fair:.2f}")
        lines.append(f"- **Recommendation:** {e.recommendation}")
        lines.append("")

    # Strategy Gaps section
    lines.append("## Strategy Gaps")
    lines.append("")
    if strategy_gaps:
        for gap in strategy_gaps:
            lines.append(f"- {gap}")
    else:
        lines.append("No gaps detected — bot covers all top trader markets.")
    lines.append("")

    return "\n".join(lines)


def format_telegram(
    leaderboard_movers: int,
    whale_moves: int,
    resolution_edges: int,
    strategy_gaps: int,
) -> str:
    """Build a concise Telegram summary (< 500 chars)."""
    return (
        f"📊 *Polymarket Intel*\n"
        f"• {leaderboard_movers} leaderboard movers tracked\n"
        f"• {whale_moves} whale moves detected\n"
        f"• {resolution_edges} resolution edge(s)\n"
        f"• {strategy_gaps} strategy gap(s)\n"
        f"Full report in Obsidian vault."
    )


# ---------------------------------------------------------------------------
# Scraping functions (require browser + network)
# ---------------------------------------------------------------------------

async def scrape_leaderboard() -> list[Trader]:
    """Scrape polymarket.com/leaderboard for top 50 traders."""
    from shared.browser import create_browser, close_browser

    browser, page = await create_browser()
    traders: list[Trader] = []

    try:
        await page.goto("https://polymarket.com/leaderboard", wait_until="networkidle", timeout=30000)
        await page.wait_for_selector("[data-testid='leaderboard-row'], table tbody tr", timeout=15000)

        rows = await page.query_selector_all("table tbody tr")
        for i, row in enumerate(rows[:50]):
            cells = await row.query_selector_all("td")
            if len(cells) < 5:
                continue

            rank_text = await cells[0].inner_text()
            username = await cells[1].inner_text()
            volume_text = await cells[2].inner_text()
            pnl_text = await cells[3].inner_text()

            def parse_money(s: str) -> float:
                s = s.strip().replace("$", "").replace(",", "").replace("+", "")
                try:
                    if "K" in s:
                        return float(s.replace("K", "")) * 1_000
                    if "M" in s:
                        return float(s.replace("M", "")) * 1_000_000
                    return float(s)
                except ValueError:
                    return 0.0

            traders.append(Trader(
                address="",
                username=username.strip(),
                rank=i + 1,
                pnl_24h=parse_money(pnl_text),
                pnl_7d=0.0,
                pnl_total=0.0,
                volume_24h=parse_money(volume_text),
                win_rate=0.0,
                trades_24h=0,
            ))
    finally:
        await close_browser(browser)

    return traders


async def scrape_trader_profiles(traders: list[Trader]) -> list[Trader]:
    """Visit top 10 trader profile pages to extract positions and markets."""
    from shared.browser import create_browser, close_browser

    browser, page = await create_browser()
    enriched = traders[:10]

    try:
        for t in enriched:
            if not t.username:
                continue
            url = f"https://polymarket.com/profile/{t.username}"
            try:
                await page.goto(url, wait_until="networkidle", timeout=20000)
                await page.wait_for_timeout(2000)

                # Extract market names from position cards
                market_els = await page.query_selector_all("[data-testid='position-market'], .market-title, h3")
                markets = []
                for el in market_els[:10]:
                    text = await el.inner_text()
                    if text.strip():
                        markets.append(text.strip())

                t.top_markets = markets[:5]
            except Exception:
                continue
    finally:
        await close_browser(browser)

    return traders


async def scrape_resolution_rules() -> list[ResolutionEdge]:
    """Browse active markets, extract resolution criteria, detect ambiguity."""
    from shared.browser import create_browser, close_browser

    browser, page = await create_browser()
    edges: list[ResolutionEdge] = []

    try:
        await page.goto("https://polymarket.com/markets", wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)

        market_links = await page.query_selector_all("a[href*='/event/']")
        urls = []
        for link in market_links[:20]:
            href = await link.get_attribute("href")
            if href and href not in urls:
                urls.append(href)

        for url in urls[:10]:
            try:
                full_url = url if url.startswith("http") else f"https://polymarket.com{url}"
                await page.goto(full_url, wait_until="networkidle", timeout=20000)
                await page.wait_for_timeout(2000)

                title_el = await page.query_selector("h1")
                title = await title_el.inner_text() if title_el else "Unknown"

                # Look for resolution rules
                body_text = await page.inner_text("body")
                rule_match = re.search(
                    r"(?:resolution|resolves?|criteria)[:\s]*(.{50,300})",
                    body_text,
                    re.IGNORECASE,
                )
                if not rule_match:
                    continue

                rule_text = rule_match.group(1).strip()

                # Check for ambiguity signals
                found_signals = [s for s in AMBIGUITY_SIGNALS if s in rule_text.lower()]
                if not found_signals:
                    continue

                # Extract price
                price_match = re.search(r"(\d+)¢", body_text)
                price = int(price_match.group(1)) / 100 if price_match else 0.50

                edges.append(ResolutionEdge(
                    market=title.strip(),
                    rule_text=rule_text[:200],
                    ambiguity=f"Contains: {', '.join(found_signals)}",
                    current_price=price,
                    estimated_fair=price,  # would need deeper analysis
                    recommendation="Review resolution criteria for edge",
                ))
            except Exception:
                continue
    finally:
        await close_browser(browser)

    return edges


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

async def run() -> None:
    """Full intel pipeline: scrape → analyze → report → deliver."""
    from shared.report import generate_pdf, get_report_dir, copy_to_obsidian
    from shared.telegram import send_summary

    print("[polymarket-intel] Scraping leaderboard...")
    traders = await scrape_leaderboard()
    print(f"[polymarket-intel] Found {len(traders)} traders")

    print("[polymarket-intel] Enriching trader profiles...")
    traders = await scrape_trader_profiles(traders)

    print("[polymarket-intel] Scanning resolution rules...")
    edges = await scrape_resolution_rules()
    print(f"[polymarket-intel] Found {len(edges)} resolution edges")

    # Analyze strategy gaps
    bot_markets = os.getenv("BOT_MARKETS", "Crypto").split(",")
    bot_markets = [m.strip() for m in bot_markets if m.strip()]
    strategy_gaps = analyze_strategy_gaps(traders, bot_markets)

    # Whale detection placeholder (would need on-chain data / API)
    whales: list[WhaleMove] = []

    # Generate report
    report_md = format_report(traders, whales, edges, strategy_gaps)

    # Save PDF + Obsidian
    report_dir = get_report_dir()
    pdf_path = report_dir / "polymarket_intel_report.pdf"
    generate_pdf(report_md, pdf_path)
    copy_to_obsidian(pdf_path)
    print(f"[polymarket-intel] PDF: {pdf_path}")

    # Telegram summary
    msg = format_telegram(
        leaderboard_movers=len(traders),
        whale_moves=len(whales),
        resolution_edges=len(edges),
        strategy_gaps=len(strategy_gaps),
    )
    await send_summary(msg)
    print("[polymarket-intel] Done.")


if __name__ == "__main__":
    asyncio.run(run())
