"""scripts/auto-update.sh — only deploys when origin/main is strictly ahead of a main checkout.

Runs the real script against a throwaway repo + bare origin under a fake $HOME.
launchctl/npm/curl/sleep are stubbed as exported bash functions (they win over the
script's hardcoded PATH), so nothing here can touch the live services.
"""
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "auto-update.sh"

STUBS = """
launchctl() { echo "launchctl $*" >> "$CALLS"; }
npm() { echo "npm $*" >> "$CALLS"; }
curl() { echo ok; }
sleep() { :; }
export -f launchctl npm curl sleep
"""


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def commit(repo, path, msg):
    f = repo / path
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(f.read_text() + msg + "\n" if f.exists() else msg + "\n")
    git(repo, "add", path)
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", msg)


@pytest.fixture
def mesh(tmp_path):
    """A fake $HOME with borina-mesh cloned from a bare origin; returns (home, repo, pusher)."""
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    pusher = tmp_path / "pusher"
    git(tmp_path, "clone", "-q", str(origin), str(pusher))
    git(pusher, "checkout", "-q", "-b", "main")
    commit(pusher, "README.md", "init")
    git(pusher, "push", "-q", "origin", "main")
    home = tmp_path / "home"
    home.mkdir()
    repo = home / "borina-mesh"
    git(tmp_path, "clone", "-q", str(origin), str(repo))
    return home, repo, pusher


def run_updater(home):
    calls = home / "calls.txt"
    calls.touch()
    env = {**os.environ, "HOME": str(home), "CALLS": str(calls)}
    subprocess.run(
        ["/bin/bash", "-c", f'{STUBS}\n/bin/bash "{SCRIPT}"'],
        env=env, check=True, capture_output=True, timeout=60,
    )
    log = home / "borina-mesh" / "logs" / "auto-update.log"
    return (log.read_text() if log.exists() else ""), calls.read_text()


def test_noop_when_main_matches_origin(mesh):
    home, _, _ = mesh
    log, calls = run_updater(home)
    assert "NEW COMMIT" not in log
    assert calls == ""


def test_deploys_when_origin_main_is_ahead(mesh):
    home, repo, pusher = mesh
    commit(pusher, "apps/api/x.py", "api change")
    git(pusher, "push", "-q", "origin", "main")

    log, calls = run_updater(home)

    assert "NEW COMMIT" in log
    assert "kickstart -k gui/" in calls and "com.borina.mesh-api" in calls
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout
    tip = subprocess.run(["git", "rev-parse", "HEAD"], cwd=pusher, capture_output=True, text=True).stdout
    assert head == tip


def test_feature_branch_checkout_never_deploys(mesh):
    """The 2026-08-23 loop: a checkout ahead of origin/main on a feature branch
    was treated as a new commit and rebuilt + restarted api/web every 120s."""
    home, repo, _ = mesh
    git(repo, "checkout", "-q", "-b", "feature/x")
    commit(repo, "apps/web/page.tsx", "local web work")
    commit(repo, "apps/api/main.py", "local api work")

    for _ in range(2):
        log, calls = run_updater(home)

    assert "NEW COMMIT" not in log
    assert calls == ""


def test_feature_branch_checkout_ignores_new_origin_commits(mesh):
    home, repo, pusher = mesh
    git(repo, "checkout", "-q", "-b", "feature/x")
    commit(pusher, "apps/api/x.py", "api change")
    git(pusher, "push", "-q", "origin", "main")

    log, calls = run_updater(home)

    assert "NEW COMMIT" not in log
    assert calls == ""


def test_unpushed_local_main_commits_never_deploy(mesh):
    home, repo, _ = mesh
    commit(repo, "apps/api/main.py", "unpushed local work")

    log, calls = run_updater(home)

    assert "NEW COMMIT" not in log
    assert calls == ""
