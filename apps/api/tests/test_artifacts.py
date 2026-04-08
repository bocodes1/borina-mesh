import pytest
from pathlib import Path
from artifacts import list_artifacts, get_artifact_path, ArtifactInfo


def test_list_artifacts_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
    result = list_artifacts()
    assert result == []


def test_list_artifacts_finds_files(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
    day_dir = tmp_path / "2026-04-08"
    day_dir.mkdir()
    (day_dir / "report.pdf").write_bytes(b"%PDF-fake")
    (day_dir / "briefing.md").write_text("# Test")

    result = list_artifacts()
    assert len(result) == 2
    names = [a.name for a in result]
    assert "report.pdf" in names
    assert "briefing.md" in names


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
