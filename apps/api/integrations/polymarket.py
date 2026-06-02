"""Polymarket — READ-ONLY surface of Bo's existing polymarket bot/agent.

We do NOT reimplement the CEX-lag edge logic here; we just read whatever the
running bot exposes (default the local :8080 dashboard API) and surface markets,
positions, and the signal/confidence it already computes. Unreachable → clean
not-connected so the panel shows "bot not running".
"""
from __future__ import annotations

from .base import IntegrationResult, env, http_get_json, not_connected, ok, safe

SOURCE = "polymarket"


def _base_url() -> str:
    # Reuse the bot's local dashboard API by default.
    return env("POLYMARKET_API_URL") or "http://localhost:8080"


def status() -> IntegrationResult:
    return ok(SOURCE, {"base_url": _base_url()})


@safe(SOURCE)
def get_overview() -> IntegrationResult:
    base = _base_url()
    raw = http_get_json(f"{base}/api/state")
    if not isinstance(raw, dict):
        return not_connected(SOURCE, "polymarket bot returned no state")
    return ok(
        SOURCE,
        {
            "markets": raw.get("markets", []),
            "positions": raw.get("positions", []),
            "signal": {
                "confidence": raw.get("confidence"),
                "edge": raw.get("edge"),
                "healthy": raw.get("healthy"),
            },
            "read_only": True,
        },
    )
