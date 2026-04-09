import pytest
from wiki_engine.schema import (
    Category, validate_frontmatter, parse_page, serialize_page, WikiPage
)


def test_all_five_categories_exist():
    assert Category.TRADING.value == "trading"
    assert Category.ECOMMERCE.value == "ecommerce"
    assert Category.BUSINESS.value == "business"
    assert Category.INFRASTRUCTURE.value == "infrastructure"
    assert Category.LESSONS.value == "lessons"


def test_validate_frontmatter_ok():
    ok, errors = validate_frontmatter({
        "category": "trading",
        "title": "Scalp exit policy",
        "created": "2026-04-09",
        "updated": "2026-04-09",
        "confidence": "high",
    })
    assert ok, errors


def test_validate_frontmatter_missing_category():
    ok, errors = validate_frontmatter({
        "title": "x",
        "created": "2026-04-09",
        "updated": "2026-04-09",
        "confidence": "high",
    })
    assert not ok
    assert any("category" in e for e in errors)


def test_validate_frontmatter_unknown_category():
    ok, errors = validate_frontmatter({
        "category": "politics",
        "title": "x",
        "created": "2026-04-09",
        "updated": "2026-04-09",
        "confidence": "high",
    })
    assert not ok


def test_validate_frontmatter_invalid_confidence():
    ok, errors = validate_frontmatter({
        "category": "trading",
        "title": "x",
        "created": "2026-04-09",
        "updated": "2026-04-09",
        "confidence": "maybe",
    })
    assert not ok
    assert any("confidence" in e for e in errors)


def test_parse_and_serialize_roundtrip():
    md = "---\ncategory: trading\ntitle: Test\ncreated: 2026-04-09\nupdated: 2026-04-09\nconfidence: high\n---\n\n# Test\n\nBody.\n"
    page = parse_page(md)
    assert page.frontmatter["category"] == "trading"
    assert "# Test" in page.body
    out = serialize_page(page)
    assert "category: trading" in out
