import os
import sys
import subprocess
import pytest
from pathlib import Path
from workers.claude_code_worker import run_worker_sync
from workers.handoff import HandoffPayload


def _init_repo(path: Path):
    subprocess.run(["git", "init"], cwd=path, check=True)
    (path / "README.md").write_text("x")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-m", "init"], cwd=path, check=True)


def test_worker_creates_worktree_and_runs(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    fake_bin = Path(__file__).parent / "fakes" / "fake_claude.py"
    monkeypatch.setenv("BORINA_CLAUDE_CMD", f"{sys.executable} {fake_bin}")
    monkeypatch.setenv("BORINA_WORKTREE_ROOT", str(tmp_path / ".borina-workers"))
    monkeypatch.setenv("BORINA_LOG_ROOT", str(tmp_path / "logs"))
    payload = HandoffPayload(
        repo_path=str(tmp_path), base_branch="master", prompt="do the thing"
    )
    result = run_worker_sync(job_id=999, payload=payload)
    assert result["exit_code"] == 0
    assert "task complete" in result["log_tail"]
    assert (tmp_path / ".borina-workers" / "999").exists()
