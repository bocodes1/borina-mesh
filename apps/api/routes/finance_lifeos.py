"""Finance Life-OS endpoints (spec §4): portfolio/net-worth, quotes, history,
news. Added as a second `/finance` router so the existing finance.py (brief,
watchlist, deep-dive) is untouched. All READ-ONLY — no order/transfer path.
"""
from fastapi import APIRouter

from integrations import brokerage, wallet, market_data
from daily_brief import sections_for, today_str

router = APIRouter(prefix="/finance", tags=["finance"])


@router.get("/portfolio")
def portfolio():
    """Net-worth strip: brokerage positions + crypto wallet. Either source may
    be 'not connected' — the tab renders a Connect-X card, never crashes."""
    broker = brokerage.get_portfolio()
    chain = wallet.get_balances()
    broker_total = (broker.data or {}).get("total_value") if broker.connected else None
    wallet_total = (chain.data or {}).get("total_usd") if chain.connected else None
    net_worth = None
    if broker_total is not None or wallet_total is not None:
        net_worth = (broker_total or 0) + (wallet_total or 0)
    return {
        "net_worth": net_worth,
        "brokerage": broker.to_dict(),
        "wallet": chain.to_dict(),
    }


@router.get("/quote/{symbol}")
def quote(symbol: str):
    return market_data.get_quote(symbol).to_dict()


@router.get("/history/{symbol}")
def history(symbol: str, range: str = "1M"):
    return market_data.get_history(symbol, range).to_dict()


@router.get("/news/{symbol}")
def news(symbol: str, limit: int = 5):
    return market_data.get_news(symbol, limit).to_dict()


@router.get("/morning")
def morning_brief_sections():
    """Finance-relevant slices of today's daily-brief (markets/movers/trading)."""
    return {
        "date": today_str(),
        "sections": sections_for(None, ["markets", "watchlist_movers", "trading"]),
    }
