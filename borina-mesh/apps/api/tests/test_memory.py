import os
import pytest


@pytest.fixture(autouse=True)
def tmp_vault(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    return tmp_path


def test_read_memory_empty():
    from memory import read_memory
    assert read_memory("ceo") == ""


def test_write_and_read_memory():
    from memory import write_memory, read_memory
    write_memory("ceo", "# CEO Memory\n\nLearned: user prefers terse output.")
    content = read_memory("ceo")
    assert "CEO Memory" in content
    assert "terse output" in content


def test_append_memory():
    from memory import write_memory, append_memory, read_memory
    write_memory("scout", "# Scout Memory\n")
    append_memory("scout", "## 2026-04-09\n- Found trending product X")
    content = read_memory("scout")
    assert "Scout Memory" in content
    assert "trending product X" in content


def test_append_memory_creates_file():
    from memory import append_memory, read_memory
    append_memory("trader", "## 2026-04-09\n- Bot health OK")
    content = read_memory("trader")
    assert "Bot health OK" in content


def test_get_memory_path():
    from memory import get_memory_path
    path = get_memory_path("ceo")
    assert path.name == "memory.md"
    assert "borina-agents" in str(path)
    assert "ceo" in str(path)
