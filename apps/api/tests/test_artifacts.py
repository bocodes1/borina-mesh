import pytest
from pathlib import Path
from artifacts import (
    list_artifacts,
    get_artifact_path,
    ArtifactInfo,
    latest_artifact_for_agent,
)


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


def test_list_artifacts_surfaces_telegram_meta(tmp_path, monkeypatch):
    import json
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
    day = tmp_path / "2026-06-05"
    day.mkdir()
    (day / "researcher-1.pdf").write_bytes(b"%PDF")
    meta_dir = day / ".telegram-meta"
    meta_dir.mkdir()
    (meta_dir / "researcher-1.pdf.json").write_text(
        json.dumps({"source": "telegram", "agent": "researcher", "prompt": "verify my stocks"})
    )

    result = list_artifacts()
    art = next(a for a in result if a.name == "researcher-1.pdf")
    assert art.source == "telegram"
    assert art.agent == "researcher"
    assert art.prompt == "verify my stocks"
    # the meta sidecar dir is not itself listed as an artifact
    assert all(a.name != "researcher-1.pdf.json" for a in result)


def test_latest_artifact_for_agent_returns_newest_body(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
    old = tmp_path / "2026-06-01"
    old.mkdir()
    (old / "researcher-00001-0900.md").write_text(
        "# researcher — Job #1\n\n## Output\n\nold digest"
    )
    new = tmp_path / "2026-06-02"
    new.mkdir()
    (new / "researcher-00002-0900.md").write_text(
        "# researcher — Job #2\n\n## Output\n\nnew digest"
    )
    body = latest_artifact_for_agent("researcher")
    assert "new digest" in body
    assert "old digest" not in body
    # only the output body is returned, not the metadata header
    assert "Job #2" not in body


def test_latest_artifact_for_agent_none(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
    assert latest_artifact_for_agent("researcher") == ""


def test_save_run_output_persists_markdown_even_with_pdf(tmp_path, monkeypatch):
    """In production weasyprint produces a PDF, but the last-artifact reader
    globs ``<agent>-*.md``. ``save_run_output`` must ALWAYS also persist the
    clean markdown body next to the PDF so ``latest_artifact_for_agent`` (used
    for context-pack grounding) finds real content on the live box."""
    import artifacts

    monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)

    # Simulate production: PDF generation succeeds (weasyprint installed).
    def _fake_pdf(pdf_path, **kwargs):
        Path(pdf_path).write_bytes(b"%PDF-fake")
        return True

    monkeypatch.setattr(artifacts, "_try_generate_pdf", _fake_pdf)

    path = artifacts.save_run_output(
        agent_id="researcher",
        job_id=7,
        prompt="do the thing",
        output="grounded digest body",
        status="completed",
    )

    # PDF stays the primary artifact (behavior unchanged).
    assert path is not None and path.suffix == ".pdf"
    # The markdown sibling now exists and the reader returns its body.
    body = latest_artifact_for_agent("researcher")
    assert "grounded digest body" in body
