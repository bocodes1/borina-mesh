import pytest
from adset_optimizer import (
    CampaignMetrics, score_campaign, generate_recommendations,
    format_report, format_telegram,
)


def make_campaign(**overrides):
    defaults = {
        "name": "CA-RCSHOPPING-1",
        "spend": 48.20,
        "impressions": 2500,
        "clicks": 135,
        "conversions": 3,
        "revenue": 135.0,
        "roas": 2.8,
        "ctr": 5.4,
        "cpc": 0.36,
        "cpa": 16.07,
        "impression_share": 42.0,
        "spend_7d_avg": 50.0,
        "roas_7d_avg": 2.4,
        "roas_trend": [2.1, 2.3, 2.2, 2.5, 2.4, 2.6, 2.8],
        "search_terms": [
            {"term": "marble coffee table", "clicks": 20, "cost": 7.0, "conversions": 2},
            {"term": "free furniture", "clicks": 12, "cost": 4.50, "conversions": 0},
            {"term": "ikea marble table", "clicks": 8, "cost": 3.00, "conversions": 0},
        ],
    }
    defaults.update(overrides)
    return CampaignMetrics(**defaults)


def test_score_campaign_green():
    c = make_campaign(roas=3.0, roas_7d_avg=2.5)
    assert score_campaign(c) == "GREEN"


def test_score_campaign_red():
    c = make_campaign(roas=0.8, roas_7d_avg=1.0)
    assert score_campaign(c) == "RED"


def test_score_campaign_yellow_declining():
    c = make_campaign(roas=1.5, roas_trend=[2.5, 2.3, 2.0, 1.8, 1.6, 1.5, 1.5])
    assert score_campaign(c) == "YELLOW"


def test_generate_recommendations_flags_wasted_spend():
    campaigns = [make_campaign()]
    recs = generate_recommendations(campaigns)
    negative_kw_recs = [r for r in recs if "negative" in r.lower()]
    assert len(negative_kw_recs) > 0


def test_format_report_has_all_sections():
    campaigns = [make_campaign()]
    recs = ["Add negative keyword: free furniture"]
    report = format_report(campaigns, recs)
    assert "Quick Stats" in report
    assert "CA-RCSHOPPING-1" in report
    assert "Ad Performance Report" in report


def test_format_telegram_is_concise():
    msg = format_telegram(spend=48.20, roas=2.8, conversions=3, status="GREEN", top_action="Add 8 negative keywords")
    assert len(msg) < 300
    assert "48.20" in msg
