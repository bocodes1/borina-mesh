from pathlib import Path
from agents import contracts
import artifacts


def test_last_artifact_text_truncates_at_max_chars(monkeypatch):
    monkeypatch.setattr(artifacts, "latest_artifact_for_agent", lambda aid: "x" * 5000)
    out = contracts.last_artifact_text("researcher", max_chars=100)
    assert out == "x" * 100


def test_last_artifact_text_empty_returns_empty_string(monkeypatch):
    monkeypatch.setattr(artifacts, "latest_artifact_for_agent", lambda aid: "")
    assert contracts.last_artifact_text("researcher") == ""


def test_load_task_spec_reads_taskmd(tmp_path, monkeypatch):
    wd = tmp_path / "researcher"
    wd.mkdir()
    (wd / "TASK.md").write_text("Write a 3-item research digest.")
    monkeypatch.setattr(contracts, "agent_workdir", lambda sid: wd)
    assert contracts.load_task_spec("researcher") == "Write a 3-item research digest."


def test_load_task_spec_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(contracts, "agent_workdir", lambda sid: tmp_path / "nope")
    assert contracts.load_task_spec("researcher") is None


def test_contracted_set_has_active_agents():
    assert {"researcher", "planner", "operator"} <= contracts.CONTRACTED
