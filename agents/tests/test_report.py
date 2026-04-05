import pytest
from pathlib import Path
from datetime import date
from shared.report import generate_pdf, get_report_dir, copy_to_obsidian


def test_get_report_dir_creates_dated_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
    report_dir = get_report_dir()
    today = date.today().isoformat()
    assert report_dir == tmp_path / today
    assert report_dir.exists()


def test_generate_pdf_creates_file(tmp_path):
    markdown = "# Test Report\n\nThis is a test.\n\n| Col1 | Col2 |\n|------|------|\n| A | B |"
    output_path = tmp_path / "test-report.pdf"
    generate_pdf(markdown, output_path)
    assert output_path.exists()
    assert output_path.stat().st_size > 0


def test_copy_to_obsidian_copies_file(tmp_path, monkeypatch):
    vault = tmp_path / "vault" / "reports"
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path / "vault"))
    src = tmp_path / "report.pdf"
    src.write_bytes(b"%PDF-fake-content")
    copy_to_obsidian(src)
    expected = vault / src.name
    assert expected.exists()
    assert expected.read_bytes() == b"%PDF-fake-content"
