"""Google OAuth lifecycle (Phase 5): consent URL → code exchange → server-side
token file → auto-refresh. Tokens never reach the frontend or URLs; the env var
GOOGLE_OAUTH_ACCESS_TOKEN still wins when set (tests / manual override)."""
import json
import time

import pytest
from fastapi.testclient import TestClient

from main import app
from integrations import google_oauth

client = TestClient(app)


@pytest.fixture(autouse=True)
def _creds(monkeypatch, tmp_path):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test-secret")
    monkeypatch.delenv("GOOGLE_OAUTH_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("GOOGLE_OAUTH_TOKEN_FILE", str(tmp_path / "tok.json"))
    yield


def _fake_post(response: dict, calls: list):
    class R:
        def raise_for_status(self):
            pass

        def json(self):
            return response

    def post(url, data=None, timeout=None):
        calls.append({"url": url, "data": data})
        return R()

    return post


def test_auth_url_requests_offline_consent():
    url = google_oauth.auth_url(state="st4te")
    assert url.startswith("https://accounts.google.com/o/oauth2/auth?")
    assert "client_id=test-client-id" in url
    assert "access_type=offline" in url and "prompt=consent" in url
    assert "state=st4te" in url
    assert "calendar.events" in url


def test_exchange_code_persists_tokens(monkeypatch):
    calls = []
    monkeypatch.setattr(
        google_oauth.httpx, "post",
        _fake_post({"access_token": "at1", "refresh_token": "rt1", "expires_in": 3600}, calls),
    )
    google_oauth.exchange_code("c0de")
    assert calls[0]["data"]["grant_type"] == "authorization_code"
    saved = json.loads(google_oauth._token_file().read_text())
    assert saved["refresh_token"] == "rt1"
    assert saved["expires_at"] > time.time()
    assert google_oauth.get_access_token() == "at1"  # fresh — no refresh needed


def test_refresh_when_expired_preserves_refresh_token(monkeypatch):
    google_oauth._save({"access_token": "old", "refresh_token": "rt1", "expires_in": -120})
    calls = []
    monkeypatch.setattr(
        google_oauth.httpx, "post",
        _fake_post({"access_token": "at2", "expires_in": 3600}, calls),  # no refresh_token in reply
    )
    assert google_oauth.get_access_token() == "at2"
    assert calls[0]["data"]["grant_type"] == "refresh_token"
    saved = json.loads(google_oauth._token_file().read_text())
    assert saved["refresh_token"] == "rt1"  # preserved across refresh


def test_no_tokens_means_empty(monkeypatch):
    assert google_oauth.get_access_token() == ""


def test_env_access_token_still_wins(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_ACCESS_TOKEN", "env-tok")
    assert google_oauth.get_access_token() == "env-tok"


def test_calendar_status_authorized_via_token_file(monkeypatch):
    google_oauth._save({"access_token": "at", "refresh_token": "rt", "expires_in": 3600})
    from integrations import google_calendar

    st = google_calendar.status()
    assert st.connected is True


# ── routes ───────────────────────────────────────────────────────────────────

def test_oauth_start_redirects_to_google():
    r = client.get("/calendar/oauth/start", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"].startswith("https://accounts.google.com/")


def test_oauth_callback_exchanges_and_confirms(monkeypatch):
    # start writes the expected state; callback must validate it.
    r = client.get("/calendar/oauth/start", follow_redirects=False)
    state = google_oauth._load_state()
    seen = {}
    monkeypatch.setattr(google_oauth, "exchange_code", lambda code: seen.setdefault("code", code))
    r = client.get(f"/calendar/oauth/callback?code=abc&state={state}")
    assert r.status_code == 200 and "connected" in r.text.lower()
    assert seen["code"] == "abc"


def test_oauth_callback_rejects_bad_state(monkeypatch):
    client.get("/calendar/oauth/start", follow_redirects=False)
    monkeypatch.setattr(google_oauth, "exchange_code", lambda code: pytest.fail("must not exchange"))
    r = client.get("/calendar/oauth/callback?code=abc&state=wrong")
    assert r.status_code == 400


def test_oauth_start_fails_without_creds(monkeypatch):
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    r = client.get("/calendar/oauth/start", follow_redirects=False)
    assert r.status_code == 400
