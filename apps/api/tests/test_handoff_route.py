import subprocess
from fastapi.testclient import TestClient
from main import app
from db import init_db


def setup_module(_):
    init_db()


def test_handoff_creates_overnight_job(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("x")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-m", "init"], cwd=tmp_path, check=True)
    client = TestClient(app)
    r = client.post("/jobs/handoff", json={
        "repo_path": str(tmp_path),
        "base_branch": "master",
        "prompt": "add a docstring"
    })
    assert r.status_code == 200
    body = r.json()
    assert body["job_id"] > 0
    assert "dashboard_url" in body


def test_handoff_rejects_non_git_dir(tmp_path):
    client = TestClient(app)
    r = client.post("/jobs/handoff", json={
        "repo_path": str(tmp_path),
        "base_branch": "main",
        "prompt": "test"
    })
    assert r.status_code == 400
