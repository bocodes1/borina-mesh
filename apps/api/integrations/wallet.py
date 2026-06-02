"""Crypto wallet — READ-ONLY balances by public address.

Keyed by WALLET_ADDRESSES (comma-separated). Queries a public explorer/RPC by
address; no private keys, no signing, no transfers. Unconfigured → clean
not-connected.
"""
from __future__ import annotations

from .base import IntegrationResult, env, http_get_json, not_connected, ok, safe

SOURCE = "wallet"
EXPLORER_URL = "https://api.blockchain.example/v1/address"  # placeholder explorer


def _addresses() -> list[str]:
    raw = env("WALLET_ADDRESSES")
    return [a.strip() for a in raw.split(",") if a.strip()]


def status() -> IntegrationResult:
    addrs = _addresses()
    if not addrs:
        return not_connected(SOURCE, "WALLET_ADDRESSES not set")
    return ok(SOURCE, {"addresses": addrs})


@safe(SOURCE)
def get_balances() -> IntegrationResult:
    addrs = _addresses()
    if not addrs:
        return not_connected(SOURCE, "WALLET_ADDRESSES not set")

    assets: dict[str, dict] = {}
    for addr in addrs:
        raw = http_get_json(f"{EXPLORER_URL}/{addr}/balances")
        for a in (raw.get("assets", []) if isinstance(raw, dict) else []):
            sym = a.get("symbol")
            if not sym:
                continue
            entry = assets.setdefault(
                sym, {"symbol": sym, "balance": 0.0, "value_usd": 0.0, "change_24h": a.get("change_24h")}
            )
            entry["balance"] += float(a.get("balance") or 0)
            entry["value_usd"] += float(a.get("value_usd") or 0)

    asset_list = sorted(assets.values(), key=lambda x: x["value_usd"], reverse=True)
    total = round(sum(a["value_usd"] for a in asset_list), 2)
    return ok(SOURCE, {"addresses": addrs, "assets": asset_list, "total_usd": total})
