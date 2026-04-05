import pytest
from ecommerce_scout import Product, score_product, rank_products, format_report, format_telegram


def make_product(**overrides):
    defaults = {
        "name": "Test Product",
        "category": "Home & Garden",
        "gmv_7d": 45000,
        "gmv_growth_pct": 120.0,
        "supplier_price_low": 12.0,
        "supplier_price_high": 15.0,
        "retail_price_low": 35.0,
        "retail_price_high": 55.0,
        "margin_pct": 40.0,
        "supplier_links": ["https://example.com/supplier1"],
        "active_advertisers": 12,
        "active_creatives": 34,
        "top_ad_description": "Lifestyle photo with family in modern living room",
        "competition_level": "Medium",
        "image_url": "",
    }
    defaults.update(overrides)
    return Product(**defaults)


def test_score_product_high_growth_high_score():
    p = make_product(gmv_growth_pct=200.0, active_creatives=50, margin_pct=45.0, active_advertisers=5)
    score = score_product(p)
    assert score > 70


def test_score_product_low_growth_low_score():
    p = make_product(gmv_growth_pct=10.0, active_creatives=2, margin_pct=15.0, active_advertisers=50)
    score = score_product(p)
    assert score < 40


def test_rank_products_returns_sorted():
    products = [
        make_product(name="Bad", gmv_growth_pct=5.0, active_creatives=1, margin_pct=10.0),
        make_product(name="Good", gmv_growth_pct=150.0, active_creatives=30, margin_pct=40.0),
        make_product(name="Great", gmv_growth_pct=200.0, active_creatives=50, margin_pct=50.0),
    ]
    ranked = rank_products(products)
    assert ranked[0].name == "Great"
    assert ranked[-1].name == "Bad"


def test_format_report_contains_product_info():
    products = [make_product(name="Cool Widget")]
    report = format_report(products)
    assert "Cool Widget" in report
    assert "Home & Garden" in report
    assert "Product Discovery Report" in report


def test_format_telegram_is_concise():
    products = [make_product(name="Cool Widget"), make_product(name="Nice Gadget")]
    summary = format_telegram(products)
    assert "Cool Widget" in summary
    assert "Nice Gadget" in summary
    assert len(summary) < 1000
