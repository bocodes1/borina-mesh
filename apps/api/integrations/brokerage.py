"""Brokerage / portfolio — READ-ONLY positions + balances.

Keyed by BROKERAGE_API_KEY/BROKERAGE_API_SECRET. No order placement, no
transfers — this module exposes no write path at all. Unconfigured → a clean
"Connect Brokerage" not-connected result.
"""
from __future__ import annotations

from .base import IntegrationResult, env, http_get_json, not_connected, ok, safe

SOURCE = "brokerage"
BASE_URL = "https://api.broker.example/v1"  # placeholder; real provider set by Bo


def _creds() -> tuple[str, str]:
    return env("BROKERAGE_API_KEY"), env("BROKERAGE_API_SECRET")


def status() -> IntegrationResult:
    key, secret = _creds()
    if not key or not secret:
        return not_connected(SOURCE, "BROKERAGE_API_KEY/SECRET not set")
    return ok(SOURCE, {"provider": "brokerage"})


@safe(SOURCE)
def get_portfolio() -> IntegrationResult:
    key, secret = _creds()
    if not key or not secret:
        return not_connected(SOURCE, "BROKERAGE_API_KEY/SECRET not set")
    raw = http_get_json(
        f"{BASE_URL}/portfolio",
        headers={"Authorization": f"Bearer {key}", "X-Api-Secret": secret},
    )
    positions = raw.get("positions", []) if isinstance(raw, dict) else []
    norm_positions = [
        {
            "symbol": p.get("symbol"),
            "qty": p.get("qty"),
            "value": p.get("market_value"),
            "day_change_pct": p.get("day_change_pct"),
        }
        for p in positions
    ]
    return ok(
        SOURCE,
        {
            "total_value": raw.get("total_value"),
            "day_change": raw.get("day_change"),
            "day_change_pct": raw.get("day_change_pct"),
            "positions": norm_positions,
            "allocation": [
                {"label": p["symbol"], "value": p["value"]}
                for p in norm_positions
                if p.get("symbol") and p.get("value") is not None
            ],
        },
    )
