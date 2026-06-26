"""Contact enrichment (Phase 1). Hunter behind IntegrationResult — stubbed, no
real network. No key → not_connected; no confident email → not_connected."""
import pytest

from integrations import contacts


def test_no_key_is_not_connected(monkeypatch):
    monkeypatch.delenv("HUNTER_API_KEY", raising=False)
    res = contacts.find_contact("Acme AI", "acme.ai")
    assert res.connected is False
    assert "HUNTER_API_KEY" in (res.error or "")


def test_find_contact_returns_best_email(monkeypatch):
    monkeypatch.setenv("HUNTER_API_KEY", "k")

    def fake_get(url, *, params=None, headers=None, timeout=None):
        return {"data": {"emails": [
            {"value": "intern@acme.ai", "first_name": "I", "last_name": "X",
             "confidence": 40, "position": "intern"},
            {"value": "founder@acme.ai", "first_name": "Ada", "last_name": "Lee",
             "confidence": 92, "position": "Founder"},
        ]}}

    monkeypatch.setattr(contacts, "http_get_json", fake_get)
    res = contacts.find_contact("Acme AI", "acme.ai")
    assert res.connected is True
    assert res.data["email"] == "founder@acme.ai"
    assert res.data["confidence"] == 92
    assert res.data["name"] == "Ada Lee"
    assert res.data["domain"] == "acme.ai"


def test_no_confident_email_is_not_connected(monkeypatch):
    monkeypatch.setenv("HUNTER_API_KEY", "k")

    def fake_get(url, *, params=None, headers=None, timeout=None):
        return {"data": {"emails": [
            {"value": "info@acme.ai", "confidence": 10, "position": "general"},
        ]}}

    monkeypatch.setattr(contacts, "http_get_json", fake_get)
    res = contacts.find_contact("Acme AI", "acme.ai")
    assert res.connected is False
    assert "confident" in (res.error or "").lower()
