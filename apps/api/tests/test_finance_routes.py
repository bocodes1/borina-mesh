"""Finance Life-OS read endpoints (spec §4)."""
from fastapi.testclient import TestClient

from main import app
from integrations import market_data

client = TestClient(app)


def test_portfolio_unconnected_envelope():
    r = client.get("/finance/portfolio")
    assert r.status_code == 200
    data = r.json()
    # No brokerage/wallet keys in tests → both not-connected, net_worth None, no crash.
    assert data["net_worth"] is None
    assert data["brokerage"]["connected"] is False
    assert data["wallet"]["connected"] is False


def test_quote_unconnected_envelope():
    r = client.get("/finance/quote/AAPL")
    assert r.status_code == 200
    assert r.json()["connected"] is False  # MARKET_DATA_API_KEY unset


def test_quote_connected(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_API_KEY", "demo")
    monkeypatch.setattr(
        market_data, "http_get_json",
        lambda *a, **k: {"c": 191.2, "d": 1.1, "dp": 0.58, "h": 192, "l": 190, "o": 190.5, "pc": 190.1},
    )
    r = client.get("/finance/quote/AAPL")
    body = r.json()
    assert body["connected"] is True and body["data"]["price"] == 191.2


def test_history_and_news_shapes(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_API_KEY", "demo")
    monkeypatch.setattr(
        market_data, "http_get_json",
        lambda url, **k: (
            {"c": [1, 2, 3], "t": [10, 20, 30]} if "candle" in url
            else [{"headline": "n", "url": "u", "source": "s", "datetime": 1}]
        ),
    )
    h = client.get("/finance/history/AAPL").json()
    assert h["connected"] is True and len(h["data"]["points"]) == 3
    n = client.get("/finance/news/AAPL").json()
    assert n["connected"] is True and n["data"][0]["title"] == "n"


def test_morning_sections_present():
    r = client.get("/finance/morning")
    assert r.status_code == 200
    sections = r.json()["sections"]
    assert set(["markets", "watchlist_movers", "trading"]).issubset(sections)
