import pytest
from pathlib import Path
from artifacts import list_artifacts, get_artifact_path, ArtifactInfo


def test_list_artifacts_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
    result = list_artifacts()
    assert result == []


def test_list_artifacts_filters_pdfs(tmp_path, monkeypatch):
    """PDFs are excluded from the Files tab listing — text-only formats surface."""
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
    day_dir = tmp_path / "2026-04-08"
    day_dir.mkdir()
    (day_dir / "report.pdf").write_bytes(b"%PDF-fake")
    (day_dir / "briefing.md").write_text("# Test")

    result = list_artifacts()
    names = [a.name for a in result]
    assert "briefing.md" in names
    assert "report.pdf" not in names


def test_list_artifacts_attributes_agent_by_filename_prefix(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
    day_dir = tmp_path / "2026-04-08"
    day_dir.mkdir()
    (day_dir / "trader-briefing.md").write_text("# Test")
    (day_dir / "polymarket-intel.md").write_text("# Test")
    (day_dir / "ceo-briefing.md").write_text("# Test")

    result = {a.name: a.agent for a in list_artifacts()}
    assert result["trader-briefing.md"] == "trader"
    assert result["polymarket-intel.md"] == "polymarket-intel"
    assert result["ceo-briefing.md"] == "ceo"


def test_list_artifacts_attributes_agent_by_export_naming(tmp_path, monkeypatch):
    """Dashboard-export naming convention `{agent}-{job:05d}-{HHMM}.md`."""
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
    day_dir = tmp_path / "2026-05-07"
    day_dir.mkdir()
    (day_dir / "trader-00006-1234.md").write_text("# job 6")
    (day_dir / "researcher-00012-0830.md").write_text("# job 12")

    result = {a.name: a.agent for a in list_artifacts()}
    assert result["trader-00006-1234.md"] == "trader"
    assert result["researcher-00012-0830.md"] == "researcher"


def test_list_artifacts_attributes_agent_by_inline_header(tmp_path, monkeypatch):
    """Filename gives no signal → fall back to the **Agent**: header in body."""
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
    day_dir = tmp_path / "2026-05-07"
    day_dir.mkdir()
    (day_dir / "morning-roundup.md").write_text(
        "# Morning Roundup\n\n**Agent**: ceo\n\nbody"
    )

    result = {a.name: a.agent for a in list_artifacts()}
    assert result["morning-roundup.md"] == "ceo"


def test_list_artifacts_uncategorized_when_unknown(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
    day_dir = tmp_path / "2026-05-07"
    day_dir.mkdir()
    (day_dir / "random-notes.md").write_text("# Just notes")

    result = {a.name: a.agent for a in list_artifacts()}
    assert result["random-notes.md"] == "uncategorized"


def test_get_artifact_path_valid(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
    day_dir = tmp_path / "2026-04-08"
    day_dir.mkdir()
    target = day_dir / "report.pdf"
    target.write_bytes(b"%PDF")

    path = get_artifact_path("2026-04-08", "report.pdf")
    assert path == target


def test_get_artifact_path_traversal_blocked(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
    with pytest.raises(ValueError, match="invalid path"):
        get_artifact_path("../../etc", "passwd")
