"""Google OAuth token lifecycle: consent URL → code exchange → auto-refresh.

Security model (spec §6): tokens live in a chmod-600 server-side JSON file
(default ``~/.borina/google_oauth_token.json``) — never the frontend, never
URLs, never the repo. Access tokens expire hourly; ``get_access_token`` "
refreshes transparently using the stored refresh_token. The env var
``GOOGLE_OAUTH_ACCESS_TOKEN`` takes precedence when set (tests / manual
override). A random ``state`` is persisted at consent-start and validated at
the callback (CSRF guard).
"""
from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

import httpx

from .base import env

AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/calendar.events"


def configured() -> bool:
    return bool(env("GOOGLE_OAUTH_CLIENT_ID") and env("GOOGLE_OAUTH_CLIENT_SECRET"))


def _token_file() -> Path:
    return Path(
        os.getenv("GOOGLE_OAUTH_TOKEN_FILE")
        or (Path.home() / ".borina" / "google_oauth_token.json")
    )


def _state_file() -> Path:
    return _token_file().with_suffix(".state")


def redirect_uri() -> str:
    return env("GOOGLE_OAUTH_REDIRECT_URI") or "http://localhost:8000/calendar/oauth/callback"


def auth_url(state: str) -> str:
    return AUTH_URI + "?" + urlencode({
        "client_id": env("GOOGLE_OAUTH_CLIENT_ID"),
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",  # ask for a refresh_token
        "prompt": "consent",       # ...even on re-consent
        "state": state,
    })


def new_state() -> str:
    state = secrets.token_urlsafe(24)
    f = _state_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(state)
    return state


def _load_state() -> str:
    f = _state_file()
    return f.read_text().strip() if f.exists() else ""


def check_state(state: str) -> bool:
    expected = _load_state()
    return bool(expected) and secrets.compare_digest(state or "", expected)


def _load() -> Optional[dict]:
    f = _token_file()
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text())
    except Exception:
        return None


def _save(tokens: dict) -> None:
    existing = _load() or {}
    # Google omits refresh_token on refresh responses — never lose the stored one.
    if not tokens.get("refresh_token") and existing.get("refresh_token"):
        tokens["refresh_token"] = existing["refresh_token"]
    tokens["expires_at"] = time.time() + int(tokens.get("expires_in", 3600)) - 60
    f = _token_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(tokens))
    try:
        f.chmod(0o600)
    except OSError:
        pass


def exchange_code(code: str) -> dict:
    resp = httpx.post(TOKEN_URI, data={
        "code": code,
        "client_id": env("GOOGLE_OAUTH_CLIENT_ID"),
        "client_secret": env("GOOGLE_OAUTH_CLIENT_SECRET"),
        "redirect_uri": redirect_uri(),
        "grant_type": "authorization_code",
    }, timeout=15)
    resp.raise_for_status()
    tokens = resp.json()
    _save(tokens)
    return tokens


def _refresh(refresh_token: str) -> dict:
    resp = httpx.post(TOKEN_URI, data={
        "client_id": env("GOOGLE_OAUTH_CLIENT_ID"),
        "client_secret": env("GOOGLE_OAUTH_CLIENT_SECRET"),
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }, timeout=15)
    resp.raise_for_status()
    tokens = resp.json()
    _save(tokens)
    return tokens


def get_access_token() -> str:
    """A currently-valid access token, refreshing if needed. "" when unauthorized."""
    override = env("GOOGLE_OAUTH_ACCESS_TOKEN")
    if override:
        return override
    tokens = _load()
    if not tokens:
        return ""
    if tokens.get("access_token") and time.time() < tokens.get("expires_at", 0):
        return tokens["access_token"]
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        return ""
    try:
        return _refresh(refresh_token).get("access_token", "")
    except Exception as exc:  # noqa: BLE001
        print(f"[google-oauth] refresh failed: {exc}")
        return ""
