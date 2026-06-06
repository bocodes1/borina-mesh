"""Files API (Phase 3 §2)."""
import json

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def _seed(tmp_path):
    day = tmp_path / "2026-06-05"
    day.mkdir()
    (day / "daily-brief.md").write_text("# brief")
    (day / "researcher-7-2026-06-05.pdf").write_bytes(b"%PDF")
    mdir = day / ".telegram-meta"
    mdir.mkdir()
    (mdir / "researcher-7-2026-06-05.pdf.json").write_text(
        json.dumps({"source": "telegram", "agent": "researcher", "prompt": "verify stocks", "job_id": 7})
    )
    (day / "notes.txt").write_text("findme content")


def test_files_lists_and_infers_source(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
    _seed(tmp_path)
    r = client.get("/files")
    assert r.status_code == 200
    data = r.json()
    byname = {f["name"]: f for f in data["files"]}
    assert byname["daily-brief.md"]["source"] == "schedule_daily"
    assert byname["daily-brief.md"]["type"] == "md"
    assert byname["researcher-7-2026-06-05.pdf"]["source"] == "telegram"
    assert byname["researcher-7-2026-06-05.pdf"]["job_id"] == 7
    assert byname["researcher-7-2026-06-05.pdf"]["prompt"] == "verify stocks"
    assert byname["notes.txt"]["source"] == "uploaded"
    assert "schedule_daily" in data["sources"]
    assert "md" in data["types"] and "txt" in data["types"]


def test_files_filters_and_search(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
    _seed(tmp_path)

    md = client.get("/files", params={"type": "md"}).json()["files"]
    assert md and all(f["type"] == "md" for f in md)

    uploaded = client.get("/files", params={"source": "uploaded"}).json()["files"]
    assert all(f["source"] == "uploaded" for f in uploaded)
    assert any(f["name"] == "notes.txt" for f in uploaded)

    found = client.get("/files", params={"q": "notes"}).json()["files"]
    names = [f["name"] for f in found]
    assert "notes.txt" in names and "daily-brief.md" not in names


def test_files_newest_first(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
    (tmp_path / "2026-06-01").mkdir()
    (tmp_path / "2026-06-01" / "old.md").write_text("x")
    (tmp_path / "2026-06-05").mkdir()
    (tmp_path / "2026-06-05" / "new.md").write_text("y")
    files = client.get("/files").json()["files"]
    assert files[0]["date"] >= files[-1]["date"]
