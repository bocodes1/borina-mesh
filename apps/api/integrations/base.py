"""Shared envelope + helpers for integrations.

The whole point: an unconfigured or failing provider yields a structured
`IntegrationResult` with `connected=False`, never an exception. Routers can
forward `.to_dict()` straight to the frontend, which renders "Connect X".
"""
from __future__ import annotations

import functools
import os
from dataclasses import dataclass
from typing import Any, Callable, Optional

import httpx

DEFAULT_TIMEOUT = 8.0


@dataclass
class IntegrationResult:
    source: str
    connected: bool
    data: Any = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "connected": self.connected,
            "data": self.data,
            "error": self.error,
        }


def ok(source: str, data: Any) -> IntegrationResult:
    return IntegrationResult(source=source, connected=True, data=data, error=None)


def not_connected(source: str, reason: str) -> IntegrationResult:
    """Provider isn't configured (missing key/address). A clean, expected state."""
    return IntegrationResult(source=source, connected=False, data=None, error=reason)


def safe(source: str) -> Callable:
    """Decorator: convert any raised exception into a graceful not-connected
    result so a provider outage never 500s a tab."""

    def deco(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs) -> IntegrationResult:
            try:
                result = fn(*args, **kwargs)
                if not isinstance(result, IntegrationResult):
                    return ok(source, result)
                return result
            except Exception as exc:  # noqa: BLE001 — graceful by design
                return IntegrationResult(
                    source=source,
                    connected=False,
                    data=None,
                    error=f"{type(exc).__name__}: {exc}",
                )

        return wrapper

    return deco


def env(key: str) -> str:
    return os.getenv(key, "").strip()


def http_get_json(
    url: str,
    *,
    params: Optional[dict] = None,
    headers: Optional[dict] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Any:
    """Thin GET→JSON used by every provider. Tests monkeypatch the module-level
    `http_get_json` reference imported into each integration to inject mocks."""
    resp = httpx.get(url, params=params, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def http_post_json(
    url: str,
    *,
    json: Optional[dict] = None,
    headers: Optional[dict] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Any:
    """Thin POST→JSON. The only write path in the integrations layer (calendar
    event creation), gated upstream on an explicit user-initiated action."""
    resp = httpx.post(url, json=json, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.json()
