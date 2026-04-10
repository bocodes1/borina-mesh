import pytest
from pathlib import Path
from wiki_engine.mutator import apply_edit, EditOp, append_to_log
from wiki_engine.paths import bootstrap_subcategory_files


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    bootstrap_subcategory_files(tmp_path)
    # Create _index.md files for each category (v3 requirement)
    for cat in ["trading", "ecommerce", "business", "infrastructure", "lessons"]:
        index = tmp_path / cat / "_index.md"
        index.write_text(
            f"---\ncategory: {cat}\ntitle: {cat.title()}\ntype: index\n---\n\n# {cat.title()}\n\n## Related Categories\n",
            encoding="utf-8",
        )
    return tmp_path


def test_append_creates_individual_page(vault):
    """v3: append creates a new individual .md file, not appending to mega file."""
    edit = EditOp(
        action="append",
        category="trading",
        subcategory="strategies",
        title="Ride-Winners Exit Policy",
        body="Hold if contract >= 65c OR momentum confirms. Exit when drops 6c from peak AND momentum reverses. Based on 39 live trades.",
        status="ACTIVE",
    )
    path = apply_edit(edit)
    assert path.exists()
    # Should be an individual file, not strategies.md
    assert path.name != "strategies.md"
    assert path.name.endswith(".md")
    content = path.read_text(encoding="utf-8")
    assert "Ride-Winners Exit Policy" in content
    assert "**Status: ACTIVE**" in content
    assert "39 live trades" in content


def test_append_creates_date_in_frontmatter(vault):
    from datetime import date
    today = date.today().isoformat()
    edit = EditOp(
        action="append",
        category="trading",
        subcategory="metrics",
        title="Q1 Win Rate",
        body="59.6% win rate on FairValueGap strategy over 50 trades.",
        status="ACTIVE",
    )
    path = apply_edit(edit)
    content = path.read_text(encoding="utf-8")
    assert today in content
    assert "Q1 Win Rate" in content


def test_append_updates_category_index(vault):
    """v3: appending a new entry adds a wikilink to _index.md."""
    edit = EditOp(
        action="append",
        category="trading",
        subcategory="strategies",
        title="My New Strategy",
        body="Some strategy content.",
        status="ACTIVE",
    )
    apply_edit(edit)
    index = (vault / "trading" / "_index.md").read_text(encoding="utf-8")
    assert "My New Strategy" in index
    assert "[[trading/" in index


def test_append_to_each_category(vault):
    subcats = [
        ("trading", "strategies", "Test Strategy"),
        ("trading", "metrics", "Test Metrics"),
        ("trading", "leaderboard", "Top Trader"),
        ("trading", "bot-config", "Bot Threshold"),
        ("ecommerce", "products", "Italian Tables"),
        ("ecommerce", "campaigns", "Meta ROAS"),
        ("ecommerce", "store", "Shopify Theme"),
        ("business", "decisions", "Budget Shift"),
        ("business", "finances", "Q1 Revenue"),
        ("infrastructure", "services", "Mac Mini IPs"),
        ("infrastructure", "automation", "Cron Schedule"),
        ("lessons", "technical", "RSI Lookback"),
        ("lessons", "operational", "Deploy Process"),
    ]
    for category, subcategory, title in subcats:
        edit = EditOp(
            action="append",
            category=category,
            subcategory=subcategory,
            title=title,
            body=f"Content for {title}.",
            status="ACTIVE",
        )
        path = apply_edit(edit)
        assert path.exists(), f"File missing for {category}/{subcategory}"
        content = path.read_text(encoding="utf-8")
        assert title in content


def test_unknown_category_raises(vault):
    with pytest.raises(ValueError, match="unknown category"):
        apply_edit(EditOp(
            action="append",
            category="politics",
            subcategory="strategies",
            title="Test",
            body="",
        ))


def test_unknown_subcategory_raises(vault):
    with pytest.raises(ValueError, match="unknown subcategory"):
        apply_edit(EditOp(
            action="append",
            category="trading",
            subcategory="nonsense",
            title="Test",
            body="",
        ))


def test_retire_entry(vault):
    """Retire marks the individual page file as retired."""
    # First append an entry
    path = apply_edit(EditOp(
        action="append",
        category="trading",
        subcategory="strategies",
        title="Old Scalp Policy",
        body="Fixed +12c scalp target. Exits at 40c.",
        status="ACTIVE",
    ))
    assert path.exists()
    # Then retire it
    retired_path = apply_edit(EditOp(
        action="retire",
        category="trading",
        subcategory="strategies",
        title="Old Scalp Policy",
        retire_reason="superseded by ride-winners exit policy",
    ))
    content = retired_path.read_text(encoding="utf-8")
    assert "retired" in content.lower()
    assert "superseded by ride-winners exit policy" in content


def test_legacy_create_still_works(vault):
    """Legacy create action (v2.0 compat) should still work."""
    from wiki_engine.schema import WikiPage, serialize_page
    edit = EditOp(
        action="create",
        category="trading",
        slug="legacy-page",
        frontmatter={
            "category": "trading",
            "title": "Legacy Page",
            "created": "2026-04-09",
            "updated": "2026-04-09",
            "confidence": "medium",
        },
        body="# Legacy Page\n\nOld style content.",
    )
    path = apply_edit(edit)
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "Legacy Page" in content


def test_append_to_log(vault):
    append_to_log("test message")
    log = (vault / "log.md").read_text(encoding="utf-8")
    assert "test message" in log
    assert "Activity Log" in log


def test_multiple_appends_same_subcategory_create_separate_files(vault):
    """v3: Multiple appends to same subcategory create SEPARATE files (not one mega file)."""
    paths = []
    for i in range(3):
        path = apply_edit(EditOp(
            action="append",
            category="trading",
            subcategory="metrics",
            title=f"Entry {i}",
            body=f"Content {i}.",
            status="ACTIVE",
        ))
        paths.append(path)

    # Each should be a separate file
    assert len(set(p.name for p in paths)) == 3, "Expected 3 distinct files"

    # Each file contains its own content
    for i, path in enumerate(paths):
        content = path.read_text(encoding="utf-8")
        assert f"Entry {i}" in content
        assert f"Content {i}" in content


def test_slug_deduplication(vault):
    """Two entries with same title get distinct slugs."""
    p1 = apply_edit(EditOp(
        action="append",
        category="trading",
        subcategory="strategies",
        title="Same Title",
        body="First.",
        status="ACTIVE",
    ))
    p2 = apply_edit(EditOp(
        action="append",
        category="trading",
        subcategory="strategies",
        title="Same Title",
        body="Second.",
        status="ACTIVE",
    ))
    assert p1.name != p2.name, "Duplicate titles must produce distinct file names"
