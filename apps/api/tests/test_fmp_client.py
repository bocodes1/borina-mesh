"""FmpClient — migrated to FMP's /stable API (legacy /api/v3 + /api/v4 retired
for accounts created after 2025-08-31).

Each test asserts the client hits the correct /stable endpoint with `symbol` as a
query param, and that the method's RETURN CONTRACT is preserved (consumers in
finance_deepdive.py / finance_screen.py are untouched), remapping any renamed
FMP fields back to the keys those consumers read.
"""
from datetime import date, timedelta

import pytest

from agents.finance_data import FmpClient, DataSourceError

STABLE = "https://financialmodelingprep.com/stable"


class _FakeResp:
    def __init__(self, data, status=200):
        self._data = data
        self.status_code = status

    def json(self):
        return self._data


class _FakeHttp:
    """Records (url, params) per call; returns queued responses in order."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def get(self, url, params=None):
        self.calls.append((url, params or {}))
        return _FakeResp(self._responses.pop(0))


def _client(responses, monkeypatch):
    monkeypatch.setenv("FMP_API_KEY", "testkey")
    c = FmpClient()
    c._client = _FakeHttp(responses)
    return c


def test_quote_uses_stable_symbol_param(monkeypatch):
    c = _client([[{"symbol": "AAPL", "price": 275.15}]], monkeypatch)
    out = c.quote("AAPL")
    url, params = c._client.calls[0]
    assert url == f"{STABLE}/quote"
    assert params["symbol"] == "AAPL"
    assert out["price"] == 275.15


def test_key_metrics_ttm(monkeypatch):
    c = _client([[{"symbol": "AAPL", "evToSalesTTM": 9.05}]], monkeypatch)
    out = c.key_metrics_ttm("AAPL")
    url, params = c._client.calls[0]
    assert url == f"{STABLE}/key-metrics-ttm"
    assert params["symbol"] == "AAPL"
    assert out["evToSalesTTM"] == 9.05


def test_key_metrics_history_passes_limit(monkeypatch):
    c = _client([[{"date": "2025-09-27"}, {"date": "2024-09-28"}]], monkeypatch)
    out = c.key_metrics_history("AAPL", years=10)
    url, params = c._client.calls[0]
    assert url == f"{STABLE}/key-metrics"
    assert params["symbol"] == "AAPL"
    assert params["limit"] == 10
    assert len(out) == 2


def test_income_statement_history_passes_limit(monkeypatch):
    c = _client([[{"date": "2025-09-27", "eps": 6.0}]], monkeypatch)
    out = c.income_statement_history("AAPL", years=5)
    url, params = c._client.calls[0]
    assert url == f"{STABLE}/income-statement"
    assert params["symbol"] == "AAPL"
    assert params["limit"] == 5
    assert out[0]["eps"] == 6.0


def test_peers_returns_flat_symbol_list(monkeypatch):
    # stable /stock-peers returns a flat list of peer objects, not {peersList:[...]}
    c = _client(
        [[{"symbol": "GOOGL"}, {"symbol": "META"}, {"symbol": "MSFT"}]],
        monkeypatch,
    )
    out = c.peers("AAPL")
    url, params = c._client.calls[0]
    assert url == f"{STABLE}/stock-peers"
    assert params["symbol"] == "AAPL"
    assert out == ["GOOGL", "META", "MSFT"]


def test_earnings_calendar_returns_next_future_date(monkeypatch):
    today = date.today()
    past = (today - timedelta(days=30)).isoformat()
    future = (today + timedelta(days=20)).isoformat()
    far = (today + timedelta(days=120)).isoformat()
    c = _client(
        [[
            {"symbol": "AAPL", "date": far, "epsActual": None},
            {"symbol": "AAPL", "date": future, "epsActual": None},
            {"symbol": "AAPL", "date": past, "epsActual": 1.5},
        ]],
        monkeypatch,
    )
    out = c.earnings_calendar("AAPL")
    url, params = c._client.calls[0]
    assert url == f"{STABLE}/earnings"
    assert params["symbol"] == "AAPL"
    assert out == date.fromisoformat(future)  # nearest upcoming, not the far one


def test_days_to_earnings(monkeypatch):
    future = (date.today() + timedelta(days=10)).isoformat()
    c = _client([[{"symbol": "AAPL", "date": future, "epsActual": None}]], monkeypatch)
    assert c.days_to_earnings("AAPL") == 10


def test_institutional_ownership_change_uses_positions_summary(monkeypatch):
    c = _client([[{"symbol": "AAPL", "investorsHoldingChange": -56}]], monkeypatch)
    out = c.institutional_ownership_change("AAPL")
    url, params = c._client.calls[0]
    assert url == f"{STABLE}/institutional-ownership/symbol-positions-summary"
    assert params["symbol"] == "AAPL"
    assert "year" in params and "quarter" in params
    assert out and out[0]["investorsHoldingChange"] == -56


def test_transcript_resolves_latest_via_dates(monkeypatch):
    # 1st call: available dates (sorted newest-first); 2nd: the transcript itself
    c = _client(
        [
            [{"quarter": 2, "fiscalYear": 2026, "date": "2026-04-30"},
             {"quarter": 1, "fiscalYear": 2026, "date": "2026-01-29"}],
            [{"symbol": "AAPL", "period": "Q2", "year": 2026, "content": "Good afternoon..."}],
        ],
        monkeypatch,
    )
    out = c.transcript("AAPL")
    dates_url, _ = c._client.calls[0]
    tx_url, tx_params = c._client.calls[1]
    assert dates_url == f"{STABLE}/earning-call-transcript-dates"
    assert tx_url == f"{STABLE}/earning-call-transcript"
    assert tx_params["year"] == 2026 and tx_params["quarter"] == 2
    assert out["content"].startswith("Good afternoon")


def test_transcript_explicit_year_quarter_skips_dates_lookup(monkeypatch):
    c = _client(
        [[{"symbol": "AAPL", "year": 2025, "content": "X"}]],
        monkeypatch,
    )
    c.transcript("AAPL", year=2025, quarter=1)
    assert len(c._client.calls) == 1
    url, params = c._client.calls[0]
    assert url == f"{STABLE}/earning-call-transcript"
    assert params["year"] == 2025 and params["quarter"] == 1


def test_earnings_history_remaps_to_consumer_fields(monkeypatch):
    # stable /earnings uses epsActual/epsEstimated; consumer reads
    # actualEarningResult/estimatedEarning — method must remap.
    c = _client(
        [[
            {"symbol": "AAPL", "date": "2026-01-29", "epsActual": 2.40, "epsEstimated": 2.35},
            {"symbol": "AAPL", "date": "2025-10-30", "epsActual": 1.64, "epsEstimated": 1.60},
        ]],
        monkeypatch,
    )
    out = c.earnings_history("AAPL", quarters=4)
    url, params = c._client.calls[0]
    assert url == f"{STABLE}/earnings"
    assert params["symbol"] == "AAPL"
    assert out[0]["actualEarningResult"] == 2.40
    assert out[0]["estimatedEarning"] == 2.35
    assert out[0]["date"] == "2026-01-29"
    assert out[0]["symbol"] == "AAPL"


def test_analyst_estimates_uses_grades_consensus(monkeypatch):
    c = _client(
        [
            [{"date": "2030-09-27", "revenueAvg": 662325750000}],  # analyst-estimates
            [{"strongBuy": 1, "buy": 69, "hold": 34, "sell": 7, "strongSell": 0, "consensus": "Buy"}],
        ],
        monkeypatch,
    )
    out = c.analyst_estimates("AAPL")
    est_url, est_params = c._client.calls[0]
    cons_url, _ = c._client.calls[1]
    assert est_url == f"{STABLE}/analyst-estimates"
    assert est_params["symbol"] == "AAPL"
    assert cons_url == f"{STABLE}/grades-consensus"
    assert out["consensus_recommendation"] == "Buy"
    assert out["buy"] == 69
    assert out["annual_estimates"]


def test_upgrades_downgrades_uses_grades_and_remaps(monkeypatch):
    c = _client(
        [[
            {"symbol": "AAPL", "date": "2026-06-22", "gradingCompany": "KGI Securities",
             "previousGrade": "Outperform", "newGrade": "Hold", "action": "downgrade"},
        ]],
        monkeypatch,
    )
    out = c.upgrades_downgrades("AAPL", limit=20)
    url, params = c._client.calls[0]
    assert url == f"{STABLE}/grades"
    assert params["symbol"] == "AAPL"
    assert params["limit"] == 20
    # consumer reads publishedDate / analystCompany / newGrade
    assert out[0]["publishedDate"] == "2026-06-22"
    assert out[0]["analystCompany"] == "KGI Securities"
    assert out[0]["newGrade"] == "Hold"


def test_insider_trades_uses_search_endpoint(monkeypatch):
    recent = (date.today() - timedelta(days=10)).isoformat()
    old = (date.today() - timedelta(days=400)).isoformat()
    c = _client(
        [[
            {"symbol": "AAPL", "transactionDate": recent, "transactionType": "S-Sale"},
            {"symbol": "AAPL", "transactionDate": old, "transactionType": "P-Purchase"},
        ]],
        monkeypatch,
    )
    out = c.insider_trades("AAPL", days_back=180)
    url, params = c._client.calls[0]
    assert url == f"{STABLE}/insider-trading/search"
    assert params["symbol"] == "AAPL"
    assert params["page"] == 0
    assert len(out) == 1  # only the recent one within 180d


def test_segment_breakdown_parses_data_key(monkeypatch):
    c = _client(
        [
            [{"symbol": "AAPL", "date": "2025-09-27", "data": {"Mac": 33708000000, "Service": 109158000000}}],
            [{"symbol": "AAPL", "date": "2025-09-27", "data": {"Americas Segment": 178353000000}}],
        ],
        monkeypatch,
    )
    out = c.segment_breakdown("AAPL")
    seg_url, seg_params = c._client.calls[0]
    geo_url, _ = c._client.calls[1]
    assert seg_url == f"{STABLE}/revenue-product-segmentation"
    assert seg_params["symbol"] == "AAPL"
    assert geo_url == f"{STABLE}/revenue-geographic-segmentation"
    assert out["segments"] == {"Mac": 33708000000, "Service": 109158000000}
    assert out["regions"] == {"Americas Segment": 178353000000}


def test_company_profile_uses_symbol_param(monkeypatch):
    c = _client([[{"symbol": "AAPL", "sector": "Technology"}]], monkeypatch)
    out = c.company_profile("AAPL")
    url, params = c._client.calls[0]
    assert url == f"{STABLE}/profile"
    assert params["symbol"] == "AAPL"
    assert out["sector"] == "Technology"


def test_institutional_holders_uses_stable_holder_endpoint(monkeypatch):
    c = _client([[{"holder": "Vanguard", "shares": 1300000000}]], monkeypatch)
    out = c.institutional_holders("AAPL", top_n=10)
    url, params = c._client.calls[0]
    assert url == f"{STABLE}/institutional-ownership/holder"
    assert params["symbol"] == "AAPL"
    assert out[0]["holder"] == "Vanguard"


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    c = FmpClient()
    with pytest.raises(DataSourceError):
        c.quote("AAPL")
