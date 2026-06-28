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
    # seeded files predate the default 7-day window; ask for the full history.
    r = client.get("/files", params={"since": "2026-06-01"})
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

    md = client.get("/files", params={"type": "md", "since": "2026-06-01"}).json()["files"]
    assert md and all(f["type"] == "md" for f in md)

    uploaded = client.get("/files", params={"source": "uploaded", "since": "2026-06-01"}).json()["files"]
    assert all(f["source"] == "uploaded" for f in uploaded)
    assert any(f["name"] == "notes.txt" for f in uploaded)

    found = client.get("/files", params={"q": "notes", "since": "2026-06-01"}).json()["files"]
    names = [f["name"] for f in found]
    assert "notes.txt" in names and "daily-brief.md" not in names


def test_files_newest_first(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
    (tmp_path / "2026-06-01").mkdir()
    (tmp_path / "2026-06-01" / "old.md").write_text("x")
    (tmp_path / "2026-06-05").mkdir()
    (tmp_path / "2026-06-05" / "new.md").write_text("y")
    files = client.get("/files", params={"since": "2026-06-01"}).json()["files"]
    assert files[0]["date"] >= files[-1]["date"]


def test_files_default_window_excludes_old_files(tmp_path, monkeypatch):
    """Without an explicit `since`, the endpoint only ships the recent window
    (last 7 days) so it never streams the whole ~2,700-file registry."""
    from datetime import date, timedelta

    monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
    old_day = (date.today() - timedelta(days=60)).isoformat()
    recent_day = date.today().isoformat()
    (tmp_path / old_day).mkdir()
    (tmp_path / old_day / "ancient.md").write_text("x")
    (tmp_path / recent_day).mkdir()
    (tmp_path / recent_day / "fresh.md").write_text("y")

    names = [f["name"] for f in client.get("/files").json()["files"]]
    assert "fresh.md" in names
    assert "ancient.md" not in names
    # but an explicit since reaches back to the old file
    names_all = [f["name"] for f in client.get("/files", params={"since": old_day}).json()["files"]]
    assert "ancient.md" in names_all


def test_files_limit_caps_result(tmp_path, monkeypatch):
    from datetime import date

    monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
    today = date.today().isoformat()
    (tmp_path / today).mkdir()
    for i in range(5):
        (tmp_path / today / f"file-{i}.md").write_text("x")
    data = client.get("/files", params={"limit": 2}).json()
    assert data["count"] == 2
