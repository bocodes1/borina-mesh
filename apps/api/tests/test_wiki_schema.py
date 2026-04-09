import pytest
from wiki_engine.schema import (
    Category, SUBCATEGORY_FILES,
    validate_frontmatter, parse_page, serialize_page, WikiPage
)


def test_all_five_categories_exist():
    assert Category.TRADING.value == "trading"
    assert Category.ECOMMERCE.value == "ecommerce"
    assert Category.BUSINESS.value == "business"
    assert Category.INFRASTRUCTURE.value == "infrastructure"
    assert Category.LESSONS.value == "lessons"


def test_subcategory_files_has_13_entries():
    total = sum(len(v) for v in SUBCATEGORY_FILES.values())
    assert total == 13, f"Expected 13 subcategory files, got {total}"


def test_subcategory_files_trading_keys():
    assert set(SUBCATEGORY_FILES["trading"].keys()) == {"strategies", "metrics", "leaderboard", "bot-config"}


def test_subcategory_files_ecommerce_keys():
    assert set(SUBCATEGORY_FILES["ecommerce"].keys()) == {"products", "campaigns", "store"}


def test_subcategory_files_business_keys():
    assert set(SUBCATEGORY_FILES["business"].keys()) == {"decisions", "finances"}


def test_subcategory_files_infrastructure_keys():
    assert set(SUBCATEGORY_FILES["infrastructure"].keys()) == {"services", "automation"}


def test_subcategory_files_lessons_keys():
    assert set(SUBCATEGORY_FILES["lessons"].keys()) == {"technical", "operational"}


def test_subcategory_files_all_paths_match_category():
    for category, subcats in SUBCATEGORY_FILES.items():
        for subcategory, path in subcats.items():
            assert path.startswith(f"{category}/"), f"Path {path} should start with {category}/"
            assert path.endswith(".md"), f"Path {path} should end with .md"


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
