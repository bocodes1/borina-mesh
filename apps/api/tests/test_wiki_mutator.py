import pytest
from pathlib import Path
from wiki_engine.mutator import apply_edit, EditOp, append_to_log


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    return tmp_path


def test_create_trading_page(vault):
    edit = EditOp(
        action="create",
        category="trading",
        slug="scalp-exit-policy",
        frontmatter={
            "category": "trading",
            "title": "Scalp Exit Policy",
            "created": "2026-04-09",
            "updated": "2026-04-09",
            "confidence": "high",
        },
        body="# Scalp Exit Policy\n\nExits cap at 40-50¢ based on 39 live trades.",
    )
    path = apply_edit(edit)
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "category: trading" in content
    assert "Scalp Exit Policy" in content


def test_create_in_each_category(vault):
    for category in ["trading", "ecommerce", "business", "infrastructure", "lessons"]:
        edit = EditOp(
            action="create",
            category=category,
            slug=f"test-{category}",
            frontmatter={
                "category": category,
                "title": f"Test {category}",
                "created": "2026-04-09",
                "updated": "2026-04-09",
                "confidence": "medium",
            },
            body=f"# Test {category}\n\nContent.",
        )
        path = apply_edit(edit)
        assert path.exists()
        assert category in str(path)


def test_append_to_existing_page(vault):
    # Create first
    apply_edit(EditOp(
        action="create",
        category="trading",
        slug="test",
        frontmatter={
            "category": "trading",
            "title": "Test",
            "created": "2026-04-09",
            "updated": "2026-04-09",
            "confidence": "medium",
        },
        body="# Test\n\nOriginal body.",
    ))

    # Append
    path = apply_edit(EditOp(
        action="append",
        category="trading",
        slug="test",
        frontmatter={},
        body="## Update\n\nNew insight added.",
    ))
    content = path.read_text(encoding="utf-8")
    assert "Original body." in content
    assert "New insight added." in content


def test_unknown_category_raises(vault):
    with pytest.raises(ValueError, match="unknown category"):
        apply_edit(EditOp(
            action="create",
            category="politics",
            slug="test",
            frontmatter={},
            body="",
        ))


def test_append_to_log(vault):
    append_to_log("test message")
    log = (vault / "log.md").read_text(encoding="utf-8")
    assert "test message" in log
    assert "Activity Log" in log
