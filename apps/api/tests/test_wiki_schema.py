import pytest
from wiki_engine.schema import (
    PageType, validate_frontmatter, parse_page, serialize_page, WikiPage
)


def test_page_types_exist():
    assert PageType.ENTITY.value == "entity"
    assert PageType.CONCEPT.value == "concept"
    assert PageType.DECISION.value == "decision"
    assert PageType.SOURCE.value == "source"


def test_validate_frontmatter_entity_ok():
    ok, errors = validate_frontmatter({
        "type": "entity",
        "status": "active",
        "created": "2026-04-09",
        "updated": "2026-04-09",
        "confidence": "high",
    })
    assert ok, errors


def test_validate_frontmatter_missing_type_fails():
    ok, errors = validate_frontmatter({"status": "active"})
    assert not ok
    assert any("type" in e for e in errors)


def test_validate_frontmatter_unknown_type_fails():
    ok, errors = validate_frontmatter({"type": "rubbish"})
    assert not ok


def test_parse_and_serialize_roundtrip():
    md = "---\ntype: entity\nstatus: active\ncreated: 2026-04-09\nupdated: 2026-04-09\nconfidence: high\n---\n\n# Test Entity\n\nBody here.\n"
    page = parse_page(md)
    assert isinstance(page, WikiPage)
    assert page.frontmatter["type"] == "entity"
    assert "Test Entity" in page.body
    out = serialize_page(page)
    assert "type: entity" in out
    assert "# Test Entity" in out
