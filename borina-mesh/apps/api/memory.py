"""Agent memory — file-based I/O against the Obsidian vault."""

import os
from pathlib import Path

MEMORY_DIR = "borina-agents"


def _vault_root() -> Path:
    vault = os.getenv("OBSIDIAN_VAULT_PATH", "")
    return Path(vault) if vault else Path("./vault")


def get_memory_path(agent_id: str) -> Path:
    """Return the path to an agent's memory file."""
    return _vault_root() / MEMORY_DIR / agent_id / "memory.md"


def read_memory(agent_id: str) -> str:
    """Read an agent's memory file. Returns empty string if missing."""
    path = get_memory_path(agent_id)
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def write_memory(agent_id: str, content: str) -> None:
    """Overwrite an agent's memory file."""
    path = get_memory_path(agent_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def append_memory(agent_id: str, entry: str) -> None:
    """Append an entry to an agent's memory file. Creates file if missing."""
    path = get_memory_path(agent_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = path.read_text(encoding="utf-8")
    else:
        existing = f"# {agent_id} Memory\n"
    path.write_text(existing + "\n" + entry + "\n", encoding="utf-8")
