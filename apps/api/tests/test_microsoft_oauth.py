"""Microsoft OAuth lifecycle (Phase 0): consent URL → code exchange → server-side
token file → auto-refresh. Mirrors test_google_oauth. Tokens never reach the
frontend or URLs; MICROSOFT_OAUTH_ACCESS_TOKEN wins when set (tests/override)."""
import json
import time

import pytest

from integrations import microsoft_oauth as mso


@pytest.fixture(autouse=True)
def _creds(monkeypatch, tmp_path):
    monkeypatch.setenv("MICROSOFT_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("MICROSOFT_OAUTH_CLIENT_SECRET", "test-secret")
    monkeypatch.delenv("MICROSOFT_OAUTH_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("MICROSOFT_OAUTH_TOKEN_FILE", str(tmp_path / "ms_tok.json"))
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


def test_configured_requires_both_creds(monkeypatch):
    assert mso.configured() is True
    monkeypatch.delenv("MICROSOFT_OAUTH_CLIENT_ID", raising=False)
    assert mso.configured() is False


def test_auth_url_requests_offline_consent():
    url = mso.auth_url(state="st4te")
    assert url.startswith("https://login.microsoftonline.com/common/oauth2/v2.0/authorize?")
    assert "client_id=test-client-id" in url
    assert "access_type=offline" in url
    assert "state=st4te" in url
    assert "Mail.Send" in url and "offline_access" in url


def test_exchange_code_persists_tokens(monkeypatch):
    calls = []
    monkeypatch.setattr(
        mso.httpx, "post",
        _fake_post({"access_token": "at1", "refresh_token": "rt1", "expires_in": 3600}, calls),
    )
    mso.exchange_code("c0de")
    assert calls[0]["data"]["grant_type"] == "authorization_code"
    saved = json.loads(mso._token_file().read_text())
    assert saved["refresh_token"] == "rt1"
    assert saved["expires_at"] > time.time()
    assert mso.get_access_token() == "at1"


def test_refresh_when_expired_preserves_refresh_token(monkeypatch):
    mso._save({"access_token": "old", "refresh_token": "rt1", "expires_in": -120})
    calls = []
    monkeypatch.setattr(
        mso.httpx, "post",
        _fake_post({"access_token": "at2", "expires_in": 3600}, calls),
    )
    assert mso.get_access_token() == "at2"
    assert calls[0]["data"]["grant_type"] == "refresh_token"
    saved = json.loads(mso._token_file().read_text())
    assert saved["refresh_token"] == "rt1"


def test_no_tokens_means_empty(monkeypatch):
    assert mso.get_access_token() == ""


def test_env_access_token_still_wins(monkeypatch):
    monkeypatch.setenv("MICROSOFT_OAUTH_ACCESS_TOKEN", "env-tok")
    assert mso.get_access_token() == "env-tok"


def test_check_state_round_trip():
    st = mso.new_state()
    assert mso.check_state(st) is True
    assert mso.check_state("wrong") is False
