import pytest
from polymarket_intel import (
    Trader, WhaleMove, ResolutionEdge,
    classify_trader, format_report, format_telegram,
    analyze_strategy_gaps,
)


def make_trader(**overrides):
    defaults = {
        "address": "0xabc123",
        "username": "trader1",
        "rank": 1,
        "pnl_24h": 12400.0,
        "pnl_7d": 45000.0,
        "pnl_total": 150000.0,
        "volume_24h": 890000.0,
        "win_rate": 62.1,
        "trades_24h": 50,
        "top_markets": ["Fed Rate Cut", "BTC Price"],
        "positions": [],
    }
    defaults.update(overrides)
    return Trader(**defaults)


def test_classify_trader_hft():
    t = make_trader(trades_24h=500, volume_24h=2000000)
    assert classify_trader(t) == "HFT Bot"


def test_classify_trader_swing():
    t = make_trader(trades_24h=5, volume_24h=50000)
    assert classify_trader(t) == "Swing Trader"


def test_classify_trader_event_specialist():
    t = make_trader(trades_24h=20, volume_24h=100000, top_markets=["Election", "Election", "Election"])
    assert classify_trader(t) == "Event Specialist"


def test_analyze_strategy_gaps():
    traders = [
        make_trader(top_markets=["Crypto", "Politics", "Sports"]),
        make_trader(top_markets=["Crypto", "Politics", "Tech"]),
    ]
    bot_markets = ["Crypto"]
    gaps = analyze_strategy_gaps(traders, bot_markets)
    assert "Politics" in gaps
    assert "Crypto" not in gaps


def test_format_report_contains_sections():
    traders = [make_trader()]
    whales = [WhaleMove(
        address="0xdef", market="Fed Rate Cut", side="YES",
        size_usd=5200, price=0.42, market_avg_price=0.45,
        is_contrarian=True,
    )]
    edges = [ResolutionEdge(
        market="Will X happen?", rule_text="Resolves YES if announced",
        ambiguity="Definition of announced unclear",
        current_price=0.65, estimated_fair=0.80,
        recommendation="Small YES position",
    )]
    report = format_report(traders, whales, edges, ["Politics", "Sports"])
    assert "Leaderboard" in report
    assert "Whale" in report
    assert "Resolution" in report
    assert "Strategy" in report


def test_format_telegram_is_concise():
    msg = format_telegram(
        leaderboard_movers=3, whale_moves=2,
        resolution_edges=1, strategy_gaps=2,
    )
    assert len(msg) < 500
