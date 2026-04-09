import pytest
import json
from pathlib import Path
from wiki_engine.mutator import apply_edit, EditOp
from wiki_engine.audit import log_approved, log_rejected


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    return tmp_path


def test_create_entity_page(vault):
    edit = EditOp(
        action="create",
        page_type="entity",
        slug="borina-mesh",
        frontmatter={
            "type": "entity",
            "status": "active",
            "created": "2026-04-09",
            "updated": "2026-04-09",
        },
        body="# Borina Mesh\n\nMulti-agent command center.",
    )
    path = apply_edit(edit)
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "type: entity" in content
    assert "# Borina Mesh" in content


def test_append_to_existing(vault):
    entity_dir = vault / "entities"
    entity_dir.mkdir(parents=True)
    (entity_dir / "test.md").write_text(
        "---\ntype: entity\nstatus: active\ncreated: 2026-04-09\nupdated: 2026-04-09\n---\n\n# Test\n\nOriginal.\n",
        encoding="utf-8"
    )

    edit = EditOp(
        action="append",
        page_type="entity",
        slug="test",
        frontmatter={},
        body="\n## Update\n\nNew info appended.\n",
    )
    path = apply_edit(edit)
    content = path.read_text(encoding="utf-8")
    assert "Original." in content
    assert "New info appended." in content


def test_log_approved_writes_jsonl(vault):
    log_approved(
        proposal_id="abc123",
        reason="valuable decision record",
        edits=[{"action": "create", "page_type": "decision", "slug": "test"}],
    )
    log_file = vault / "_queue" / "approved.jsonl"
    assert log_file.exists()
    line = log_file.read_text(encoding="utf-8").strip()
    record = json.loads(line)
    assert record["proposal_id"] == "abc123"


def test_log_rejected_writes_jsonl(vault):
    log_rejected(
        proposal_id="def456",
        reason="routine session log, no signal",
    )
    log_file = vault / "_queue" / "rejected.jsonl"
    assert log_file.exists()
    record = json.loads(log_file.read_text(encoding="utf-8").strip())
    assert record["proposal_id"] == "def456"
