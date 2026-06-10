"""Write a completed dispatch into the Obsidian vault (spec: Bo 2026-06-10,
"it should save the things it works on").

Report file: 04-resources/reports/{day}-{agent}-job{job_id}.md with
frontmatter; a link line is appended to 01-daily/{day}.md under
"## Mesh outputs" (note + section created if missing). Returns the report
path, or None when no vault is configured or on ANY error — write-back must
never break a dispatch reply.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

_DAILY_TEMPLATE = """---
title: '{day}'
type: daily
tags: [daily]
---

# {day} Session Notes

## Mesh outputs
"""


def _slug(agent: str, job_id: int, day: str) -> str:
    safe_agent = re.sub(r"[^a-z0-9-]", "", agent.lower()) or "agent"
    return f"{day}-{safe_agent}-job{job_id}"


def save_dispatch_to_vault(
    agent: str, prompt: str, markdown: str, day: str, job_id: int
) -> Optional[Path]:
    root = os.getenv("OBSIDIAN_VAULT_PATH", "").strip()
    if not root:
        return None
    try:
        vault = Path(root)
        stem = _slug(agent, job_id, day)

        report = vault / "04-resources" / "reports" / f"{stem}.md"
        report.parent.mkdir(parents=True, exist_ok=True)
        prompt_line = prompt.replace("\n", " ")[:200]
        report.write_text(
            "---\n"
            f"title: '{stem}'\n"
            "type: mesh-report\n"
            f"agent: {agent}\n"
            f"date: {day}\n"
            f"prompt: '{prompt_line.replace(chr(39), chr(34))}'\n"
            "tags: [mesh-report]\n"
            "---\n\n"
            f"{markdown.strip()}\n\n"
            f"Back to [[{day}]]\n"
        )

        daily = vault / "01-daily" / f"{day}.md"
        daily.parent.mkdir(parents=True, exist_ok=True)
        text = daily.read_text() if daily.exists() else _DAILY_TEMPLATE.format(day=day)
        if "## Mesh outputs" not in text:
            text += "\n## Mesh outputs\n"
        text += f"- [[reports/{stem}]] — {agent}: {prompt_line[:80]}\n"
        daily.write_text(text)
        return report
    except Exception as exc:  # noqa: BLE001 — never break the reply path
        print(f"[vault-writeback] failed: {exc}")
        return None
