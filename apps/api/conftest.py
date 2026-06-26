"""Pytest bootstrap: isolate the test database from the live borina.db.

db.py reads DATABASE_URL at import time, so this must run before any
`import db` / `import main`. conftest is imported by pytest before test
modules, so setting the env var here points every test at a throwaway DB
and leaves the production borina.db (used by the running service) untouched.
"""
import os
import pathlib
import tempfile

_TEST_DB = pathlib.Path(tempfile.gettempdir()) / "borina_test.db"
# Start from a clean schema each session.
try:
    _TEST_DB.unlink()
except FileNotFoundError:
    pass

os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB}"

# Isolate filesystem-backed state from the real machine so tests are hermetic
# and never see (or write) the live obsidian-vault or reports dir. The vault is
# disabled by default (empty) — individual tests that exercise the wiki/vault
# set their own OBSIDIAN_VAULT_PATH via monkeypatch.
_TEST_REPORTS = pathlib.Path(tempfile.mkdtemp(prefix="borina_test_reports_"))
os.environ["OBSIDIAN_VAULT_PATH"] = ""
os.environ["REPORTS_DIR"] = str(_TEST_REPORTS)
# Keep tests away from the real ~/.borina Google OAuth token file.
os.environ["GOOGLE_OAUTH_TOKEN_FILE"] = str(_TEST_REPORTS / "google_oauth_token.json")

# Deterministic, credential-free defaults so integration wrappers take their
# "not connected" path and tests never reach a real external service.
os.environ.setdefault("CORS_ORIGINS", "http://localhost:3000")
os.environ.setdefault("INTENT_CONFIDENCE_THRESHOLD", "0.6")

import pytest  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _init_test_db():
    """Create tables once for the isolated DB. Import `models` first so EVERY
    table model is registered with SQLModel.metadata before create_all — without
    this, running a single test file (that doesn't transitively import a given
    model) would leave its table missing."""
    import models  # noqa: F401 — registers Job/AgentRun/AgentConfig/PlanItem/Task/...
    from db import init_db

    init_db()
    yield


@pytest.fixture(autouse=True)
def _isolate_fs_env(monkeypatch):
    """Reset filesystem-backed env before every test so cross-test leakage
    (e.g. test_wiki_routes sets OBSIDIAN_VAULT_PATH at module import) can't
    bleed real artifacts into hermetic tests. Tests that need a vault/reports
    dir override these with their own monkeypatch in-body (runs after this).
    """
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", "")
    monkeypatch.setenv("REPORTS_DIR", str(_TEST_REPORTS))
    # Redirect the agent workdir root to a throwaway dir so tests that read an
    # agent's file handoff (e.g. planner._agent_plan_file) can't pick up a real
    # plan file left by a live run on this machine. Resolved at call time via
    # `from agents.runner_v2 import _workdir_root`, so patching the module attr
    # is enough.
    import agents.runner_v2 as _runner_v2

    monkeypatch.setattr(_runner_v2, "_workdir_root", lambda: _TEST_REPORTS / "agents")
    yield
