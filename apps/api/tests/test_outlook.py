"""Outlook send transport (Phase 1). The single outbound path: send_mail HARD
refuses unless user_initiated=True. Graph/Browser backends are stubbed — no real
network in tests. Mirrors the google_calendar create_event gate."""
import pytest

from integrations import outlook
from integrations import microsoft_oauth as mso


@pytest.fixture(autouse=True)
def _creds(monkeypatch):
    monkeypatch.setenv("MICROSOFT_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("MICROSOFT_OAUTH_CLIENT_SECRET", "sec")
    monkeypatch.setenv("MICROSOFT_OAUTH_ACCESS_TOKEN", "tok")
    monkeypatch.setenv("OUTLOOK_SEND_TRANSPORT", "graph")
    yield


def test_send_mail_refuses_without_user_initiated():
    res = outlook.send_mail(["a@b.com"], "Hi", "Body")
    assert res.connected is False
    assert "explicit user action" in (res.error or "")


def test_send_mail_refuses_even_when_authorized():
    # Authorized but no user action → still refuses (the invariant).
    res = outlook.send_mail(["a@b.com"], "Hi", "Body", user_initiated=False)
    assert res.connected is False


def test_send_mail_not_connected_when_unauthorized(monkeypatch):
    monkeypatch.delenv("MICROSOFT_OAUTH_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr(mso, "get_access_token", lambda: "")
    res = outlook.send_mail(["a@b.com"], "Hi", "Body", user_initiated=True)
    assert res.connected is False
    assert "not authorized" in (res.error or "").lower()


def test_send_mail_graph_success_with_user_initiated(monkeypatch):
    sent = {}

    def fake_post(url, *, json=None, headers=None, timeout=None):
        sent["url"] = url
        sent["json"] = json
        sent["auth"] = (headers or {}).get("Authorization")
        return {}  # Graph sendMail returns 202 with empty body

    monkeypatch.setattr(outlook, "http_post_json", fake_post)
    res = outlook.send_mail(["a@b.com"], "Subj", "Hello", user_initiated=True)
    assert res.connected is True
    assert res.data["via"] == "graph"
    assert sent["url"].endswith("/me/sendMail")
    assert sent["json"]["message"]["subject"] == "Subj"
    assert sent["json"]["message"]["toRecipients"][0]["emailAddress"]["address"] == "a@b.com"
    assert sent["auth"] == "Bearer tok"


def test_browser_sender_used_when_transport_browser(monkeypatch):
    monkeypatch.setenv("OUTLOOK_SEND_TRANSPORT", "browser")
    captured = {}

    def fake_browser_send(self, recipients, subject, body, attachments):
        captured["recipients"] = recipients
        return {"id": "browser-1"}

    monkeypatch.setattr(outlook.BrowserSender, "send", fake_browser_send)
    res = outlook.send_mail(["x@y.com"], "S", "B", user_initiated=True)
    assert res.connected is True
    assert res.data["via"] == "browser"
    assert captured["recipients"] == ["x@y.com"]
