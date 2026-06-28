"""Integration wrapper contract tests (spec §10b).

Each provider must: (1) return connected=False (never raise) when its key is
absent, (2) return sane data when configured + its HTTP call is mocked,
(3) degrade gracefully (connected=False) if the upstream call raises.
Calendar create must refuse unless user_initiated=True.
"""
import pytest

from integrations import market_data, brokerage, wallet, weather, google_calendar


# ── not-connected when unkeyed (conftest leaves these env vars unset) ────────
def test_market_data_not_connected(monkeypatch):
    monkeypatch.delenv("MARKET_DATA_API_KEY", raising=False)
    r = market_data.get_quote("AAPL")
    assert r.connected is False and r.data is None and r.error


def test_brokerage_not_connected(monkeypatch):
    monkeypatch.delenv("BROKERAGE_API_KEY", raising=False)
    monkeypatch.delenv("BROKERAGE_API_SECRET", raising=False)
    assert brokerage.get_portfolio().connected is False


def test_wallet_not_connected(monkeypatch):
    monkeypatch.delenv("WALLET_ADDRESSES", raising=False)
    assert wallet.get_balances().connected is False


def test_weather_not_connected(monkeypatch):
    for k in ("WEATHER_API_KEY", "HOME_LAT", "HOME_LON"):
        monkeypatch.delenv(k, raising=False)
    assert weather.get_current().connected is False


def test_google_calendar_not_connected(monkeypatch):
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    assert google_calendar.list_events("a", "b").connected is False


# ── connected + sane data when configured and HTTP mocked ────────────────────
def test_market_data_quote_ok(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_API_KEY", "demo")
    monkeypatch.setattr(
        market_data, "http_get_json",
        lambda *a, **k: {"c": 191.2, "d": 1.1, "dp": 0.58, "h": 192, "l": 190, "o": 190.5, "pc": 190.1},
    )
    r = market_data.get_quote("aapl")
    assert r.connected is True
    assert r.data["symbol"] == "AAPL" and r.data["price"] == 191.2 and r.data["change_pct"] == 0.58


def test_market_data_news_ok(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_API_KEY", "demo")
    monkeypatch.setattr(
        market_data, "http_get_json",
        lambda *a, **k: [{"headline": "X", "url": "u", "source": "s", "datetime": 1}],
    )
    r = market_data.get_news("AAPL")
    assert r.connected is True and r.data[0]["title"] == "X"


def test_brokerage_portfolio_ok(monkeypatch):
    monkeypatch.setenv("BROKERAGE_API_KEY", "k")
    monkeypatch.setenv("BROKERAGE_API_SECRET", "s")
    monkeypatch.setattr(
        brokerage, "http_get_json",
        lambda *a, **k: {
            "total_value": 1000, "day_change": 10, "day_change_pct": 1.0,
            "positions": [{"symbol": "AAPL", "qty": 2, "market_value": 400, "day_change_pct": 0.5}],
        },
    )
    r = brokerage.get_portfolio()
    assert r.connected is True and r.data["total_value"] == 1000
    assert r.data["allocation"][0] == {"label": "AAPL", "value": 400}


def test_wallet_balances_ok(monkeypatch):
    monkeypatch.setenv("WALLET_ADDRESSES", "0xabc, 0xdef")
    monkeypatch.setattr(
        wallet, "http_get_json",
        lambda *a, **k: {"assets": [{"symbol": "ETH", "balance": 1, "value_usd": 3000, "change_24h": 2.1}]},
    )
    r = wallet.get_balances()
    assert r.connected is True
    # two addresses summed
    assert r.data["assets"][0]["symbol"] == "ETH" and r.data["total_usd"] == 6000.0


def test_weather_ok(monkeypatch):
    monkeypatch.setenv("WEATHER_API_KEY", "k")
    monkeypatch.setenv("HOME_LAT", "40.7")
    monkeypatch.setenv("HOME_LON", "-74.0")
    monkeypatch.setattr(
        weather, "http_get_json",
        lambda *a, **k: {"weather": [{"main": "Clouds", "description": "broken"}],
                          "main": {"temp": 60, "feels_like": 58, "humidity": 70}, "name": "NYC"},
    )
    r = weather.get_current()
    assert r.connected is True and r.data["temp"] == 60 and r.data["conditions"] == "Clouds"


def test_google_calendar_list_ok(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_OAUTH_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(
        google_calendar, "http_get_json",
        lambda *a, **k: {"items": [{"id": "1", "summary": "Standup",
                                     "start": {"dateTime": "2026-06-02T09:00:00Z"},
                                     "end": {"dateTime": "2026-06-02T09:15:00Z"}}]},
    )
    r = google_calendar.list_events("a", "b")
    assert r.connected is True and r.data[0]["title"] == "Standup"


# ── graceful: never raises on upstream failure ───────────────────────────────
def test_integration_never_raises(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_API_KEY", "demo")

    def boom(*a, **k):
        raise RuntimeError("upstream 503")

    monkeypatch.setattr(market_data, "http_get_json", boom)
    r = market_data.get_quote("AAPL")
    assert r.connected is False and "upstream 503" in r.error


# ── safety: calendar create refuses unless user-initiated ────────────────────
def test_calendar_create_refused_without_user_action(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_OAUTH_ACCESS_TOKEN", "tok")

    def fail_post(*a, **k):
        raise AssertionError("create must not POST when not user-initiated")

    monkeypatch.setattr(google_calendar, "http_post_json", fail_post)
    r = google_calendar.create_event({"summary": "x"}, user_initiated=False)
    assert r.connected is False and "explicit user action" in r.error


def test_calendar_create_allowed_when_user_initiated(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_OAUTH_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(
        google_calendar, "http_post_json",
        lambda *a, **k: {"id": "evt1", "htmlLink": "http://cal/evt1"},
    )
    r = google_calendar.create_event({"summary": "x"}, user_initiated=True)
    assert r.connected is True and r.data["id"] == "evt1"
