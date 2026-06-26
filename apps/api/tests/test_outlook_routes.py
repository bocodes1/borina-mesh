"""Outlook routes (Phase 0): OAuth consent flow + the one-shot send-validation
path. The POST hard-gates user_initiated so an agent/non-UI path can never send.
Mirrors test_google_oauth route tests + the calendar create gate."""
import pytest
from fastapi.testclient import TestClient

from main import app
from integrations import microsoft_oauth as mso
from integrations import outlook

client = TestClient(app)


@pytest.fixture(autouse=True)
def _creds(monkeypatch, tmp_path):
    monkeypatch.setenv("MICROSOFT_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("MICROSOFT_OAUTH_CLIENT_SECRET", "sec")
    monkeypatch.setenv("MICROSOFT_OAUTH_TOKEN_FILE", str(tmp_path / "ms_tok.json"))
    monkeypatch.delenv("MICROSOFT_OAUTH_ACCESS_TOKEN", raising=False)
    yield


def test_send_rejects_without_user_initiated(monkeypatch):
    def must_not_send(*a, **k):
        pytest.fail("send_mail must not be called without user_initiated")

    monkeypatch.setattr(outlook, "send_mail", must_not_send)
    r = client.post("/outlook/send", json={
        "recipients": ["a@b.com"], "subject": "S", "body": "B",
    })
    assert r.status_code == 403


def test_send_passes_user_initiated_true(monkeypatch):
    calls = []

    def spy(recipients, subject, body, *, attachments=None, user_initiated=False, send_via=None):
        calls.append({"user_initiated": user_initiated, "recipients": recipients})
        from integrations.base import ok
        return ok("outlook", {"id": "x", "via": "graph"})

    monkeypatch.setattr(outlook, "send_mail", spy)
    r = client.post("/outlook/send", json={
        "recipients": ["a@b.com"], "subject": "S", "body": "B",
        "user_initiated": True,
    })
    assert r.status_code == 201
    assert len(calls) == 1 and calls[0]["user_initiated"] is True


def test_oauth_start_redirects_to_microsoft():
    r = client.get("/outlook/oauth/start", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"].startswith("https://login.microsoftonline.com/")


def test_oauth_callback_exchanges_and_confirms(monkeypatch):
    client.get("/outlook/oauth/start", follow_redirects=False)
    state = mso._load_state()
    seen = {}
    monkeypatch.setattr(mso, "exchange_code", lambda code: seen.setdefault("code", code))
    r = client.get(f"/outlook/oauth/callback?code=abc&state={state}")
    assert r.status_code == 200 and "connected" in r.text.lower()
    assert seen["code"] == "abc"


def test_oauth_callback_rejects_bad_state(monkeypatch):
    client.get("/outlook/oauth/start", follow_redirects=False)
    monkeypatch.setattr(mso, "exchange_code", lambda code: pytest.fail("must not exchange"))
    r = client.get("/outlook/oauth/callback?code=abc&state=wrong")
    assert r.status_code == 400


def test_oauth_start_fails_without_creds(monkeypatch):
    monkeypatch.delenv("MICROSOFT_OAUTH_CLIENT_ID", raising=False)
    r = client.get("/outlook/oauth/start", follow_redirects=False)
    assert r.status_code == 400
