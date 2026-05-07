"""Artifact storage — serves agent reports for the Files tab.

Reports are read from REPORTS_DIR (and merged with `{vault}/reports/` if
OBSIDIAN_VAULT_PATH is set) so the dashboard surfaces artifacts from all
machines via Obsidian Sync.

Outputs are written as markdown — the readable source-of-truth. PDFs are not
generated here anymore (the Files tab is for *reading*, not for downloading
prerendered exports).
"""

import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


# Agent ids we know about — used to attribute legacy files whose names don't
# follow the dashboard convention `{agent_id}-{job:05d}-{HHMM}.md`.
_KNOWN_AGENTS = (
    "trader",
    "polymarket-intel",
    "inbox-triage",
    "ceo",
    "ecommerce-scout",
    "scout",
    "researcher",
    "adset-optimizer",
    "adset",
    "qa-director",
    "wiki-curator",
)

# Files we surface in the Files tab. PDFs are intentionally excluded — they're
# legacy export artifacts, not the readable source.
_READABLE_EXTS = {".md", ".txt", ".json", ".csv"}

# Filename prefix → canonical agent id. Order matters (longest prefix first).
_PREFIX_TO_AGENT = (
    ("polymarket-intel", "polymarket-intel"),
    ("polymarket-elite", "trader"),  # trader's deep-research output
    ("polymarket", "polymarket-intel"),
    ("inbox-triage", "inbox-triage"),
    ("inbox", "inbox-triage"),
    ("ecommerce-scout", "ecommerce-scout"),
    ("scout", "ecommerce-scout"),
    ("adset-optimizer", "adset-optimizer"),
    ("adset", "adset-optimizer"),
    ("qa-director", "qa-director"),
    ("researcher", "researcher"),
    ("trader-briefing", "trader"),
    ("trader-telegram", "trader"),
    ("trade-analysis", "trader"),
    ("trader", "trader"),
    ("ceo-briefing", "ceo"),
    ("ceo", "ceo"),
)

# Regex matches the dashboard-export naming convention: {agent}-{job:05d}-{HHMM}
_EXPORT_NAME_RE = re.compile(r"^(?P<agent>[a-z0-9][a-z0-9-]*)-\d{5}-\d{4}\.[a-z]+$")

# Inline header markers we'll peek at when filename isn't decisive.
_AGENT_HEADER_RE = re.compile(
    r"(?im)^(?:\*\*\s*)?Agent(?:\s*\*\*)?\s*[:=]\s*\*?\*?\s*([a-z0-9][a-z0-9-]+)"
)


@dataclass
class ArtifactInfo:
    date: str
    name: str
    agent: str  # detected producing agent ("uncategorized" if unknown)
    size_bytes: int
    modified: str
    path: str


def _reports_roots() -> list[Path]:
    """Return all report directories to scan (local + Obsidian vault if set)."""
    roots: list[Path] = [Path(os.getenv("REPORTS_DIR", "./reports")).resolve()]
    vault = os.getenv("OBSIDIAN_VAULT_PATH", "").strip()
    if vault:
        vault_reports = Path(vault).expanduser() / "reports"
        if vault_reports.exists():
            resolved = vault_reports.resolve()
            if resolved not in roots:
                roots.append(resolved)
    return roots


def _detect_agent(file_path: Path) -> str:
    """Best-effort attribution of a report file to a producing agent.

    1. Dashboard export convention: ``{agent}-{NNNNN}-{HHMM}.ext`` → agent id.
    2. Known prefix match (`trader-briefing.md`, `polymarket-intel.md`, …).
    3. Peek at the file's first ~40 lines for an `**Agent**: x` header.
    4. Fall back to "uncategorized".
    """
    name = file_path.name.lower()

    m = _EXPORT_NAME_RE.match(name)
    if m:
        return m.group("agent")

    for prefix, agent in _PREFIX_TO_AGENT:
        if name.startswith(prefix):
            return agent

    if file_path.suffix.lower() in {".md", ".txt"} and file_path.is_file():
        try:
            with file_path.open("r", encoding="utf-8", errors="replace") as f:
                head = "".join(next(f, "") for _ in range(40))
            m = _AGENT_HEADER_RE.search(head)
            if m:
                token = m.group(1).lower()
                # Normalise to a known agent id when possible.
                for prefix, agent in _PREFIX_TO_AGENT:
                    if token == prefix or token == agent:
                        return agent
                if token in _KNOWN_AGENTS:
                    return token
        except OSError:
            pass

    return "uncategorized"


def list_artifacts() -> list[ArtifactInfo]:
    """List every readable artifact across all date directories and roots.

    Filters out PDFs and other non-readable formats — the Files tab is for
    *reading* output, not downloading exports. If the same (date, name) exists
    in multiple roots, the most recently modified copy wins.
    """
    merged: dict[tuple[str, str], ArtifactInfo] = {}
    for root in _reports_roots():
        if not root.exists():
            continue
        for day_dir in sorted(root.iterdir(), reverse=True):
            if not day_dir.is_dir():
                continue
            for file in sorted(day_dir.iterdir()):
                if not file.is_file():
                    continue
                if file.suffix.lower() not in _READABLE_EXTS:
                    continue
                stat = file.stat()
                info = ArtifactInfo(
                    date=day_dir.name,
                    name=file.name,
                    agent=_detect_agent(file),
                    size_bytes=stat.st_size,
                    modified=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    path=f"{day_dir.name}/{file.name}",
                )
                key = (info.date, info.name)
                existing = merged.get(key)
                if existing is None or info.modified > existing.modified:
                    merged[key] = info

    # Newest date first, then filename.
    return sorted(merged.values(), key=lambda a: (a.date, a.name), reverse=True)


def get_artifact_path(date: str, name: str) -> Path:
    """Resolve a safe absolute path for an artifact.

    Searches all configured roots and returns the first match whose resolved
    path stays inside its root. Raises ValueError on traversal attempts.
    """
    if "/" in date or "\\" in date or ".." in date:
        raise ValueError("invalid path: date")
    if "/" in name or "\\" in name or ".." in name:
        raise ValueError("invalid path: name")

    last_candidate: Optional[Path] = None
    for root in _reports_roots():
        target = (root / date / name).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            raise ValueError("invalid path: escapes root")
        last_candidate = target
        if target.exists():
            return target

    if last_candidate is not None:
        return last_candidate
    raise ValueError("invalid path: no roots configured")


def save_run_output(
    agent_id: str, job_id: int, prompt: str, output: str, status: str
) -> Path | None:
    """Save an agent run's output as markdown in reports/{today}/.

    Returns the written path, or None if the output is empty. The Files tab
    surfaces these markdown files directly — no PDF rendering step.
    """
    if not output or not output.strip():
        return None

    from datetime import date, datetime as _dt
    root = Path(os.getenv("REPORTS_DIR", "./reports")).resolve()
    day_dir = root / date.today().isoformat()
    day_dir.mkdir(parents=True, exist_ok=True)

    now = _dt.now()
    safe_agent = agent_id.replace("/", "-")
    base_name = f"{safe_agent}-{job_id:05d}-{now.strftime('%H%M')}"
    md_path = day_dir / f"{base_name}.md"

    _write_markdown(
        md_path=md_path,
        agent_id=agent_id,
        job_id=job_id,
        prompt=prompt,
        output=output,
        status=status,
        timestamp=now,
    )

    # Mirror to Obsidian vault if configured so the Mac Mini and PC see the same
    # Files tab.
    vault = os.getenv("OBSIDIAN_VAULT_PATH", "").strip()
    if vault:
        try:
            vault_dir = (
                Path(vault).expanduser() / "reports" / date.today().isoformat()
            ).resolve()
            vault_dir.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy2(md_path, vault_dir / md_path.name)
        except Exception as e:
            print(f"[artifacts] Failed to copy to vault: {e}")

    return md_path


def _write_markdown(
    md_path: Path,
    agent_id: str,
    job_id: int,
    prompt: str,
    output: str,
    status: str,
    timestamp,
) -> None:
    """Write the run as a self-contained markdown document.

    Header includes Agent / Job / Status / Timestamp so `_detect_agent`
    can attribute it back even if the filename gets changed later.
    """
    lines = [
        f"# {agent_id} — Job #{job_id}",
        "",
        f"**Agent**: {agent_id}",
        f"**Status**: {status}",
        f"**Timestamp**: {timestamp.isoformat()}",
        "",
        "## Prompt",
        "",
        f"> {prompt.strip()}",
        "",
        "---",
        "",
        "## Output",
        "",
        output.strip(),
        "",
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")
