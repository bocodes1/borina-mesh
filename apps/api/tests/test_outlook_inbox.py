"""Mailbox read (Phase 3) — read-only Graph inbox fetch for reply detection.
Stubbed http_get_json (no real network). list_inbox NEVER sends. The scope now
carries Mail.Read (additive to Phase 0/1's Mail.Send). Mirrors test_contacts'
http_get_json injection + Phase 1's authorized/unauthorized branches."""
import pytest

from integrations import outlook
from integrations import microsoft_oauth as mso


@pytest.fixture(autouse=True)
def _creds(monkeypatch):
    monkeypatch.setenv("MICROSOFT_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("MICROSOFT_OAUTH_CLIENT_SECRET", "sec")
    monkeypatch.setenv("MICROSOFT_OAUTH_ACCESS_TOKEN", "tok")
    yield


def test_scope_includes_mail_read():
    assert "Mail.Read" in mso.SCOPE
    assert "Mail.Send" in mso.SCOPE  # additive — Phase 0/1 scope preserved


def test_list_inbox_not_connected_when_unauthorized(monkeypatch):
    monkeypatch.delenv("MICROSOFT_OAUTH_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr(outlook, "_access_token", lambda: "")
    res = outlook.list_inbox()
    assert res.connected is False
    assert "not authorized" in (res.error or "").lower()


def test_list_inbox_maps_graph_messages(monkeypatch):
    seen = {}

    def fake_get(url, *, params=None, headers=None, timeout=None):
        seen["url"] = url
        seen["params"] = params
        seen["auth"] = (headers or {}).get("Authorization")
        return {"value": [
            {"id": "m1", "subject": "Re: internship",
             "from": {"emailAddress": {"address": "Ada@Acme.AI", "name": "Ada Lee"}},
             "receivedDateTime": "2026-06-20T14:00:00Z", "bodyPreview": "Sure, let's chat."},
        ]}

    monkeypatch.setattr(outlook, "http_get_json", fake_get)
    res = outlook.list_inbox(since_iso="2026-06-13T00:00:00Z", top=10)
    assert res.connected is True
    assert seen["url"].endswith("/me/messages")
    assert seen["auth"] == "Bearer tok"
    msg = res.data[0]
    assert msg["from"] == "ada@acme.ai"           # lower-cased for matching
    assert msg["subject"] == "Re: internship"
    assert msg["preview"] == "Sure, let's chat."
    assert msg["received"] == "2026-06-20T14:00:00Z"


def test_list_inbox_handles_missing_from(monkeypatch):
    def fake_get(url, *, params=None, headers=None, timeout=None):
        return {"value": [{"id": "m2", "subject": "No sender", "receivedDateTime": "x"}]}

    monkeypatch.setattr(outlook, "http_get_json", fake_get)
    res = outlook.list_inbox()
    assert res.connected is True
    assert res.data[0]["from"] == ""             # graceful, never crashes
