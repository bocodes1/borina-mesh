"""Dispatcher (spec §8b.4).

Resolved intent → run the chosen agent through the existing tmux session pool →
markdown→PDF (WeasyPrint) → register as a `/artifacts` artifact tagged
`source: telegram` → reply on Telegram (summary + PDF + dashboard deep-link).

External effects (`run_agent`, `render_markdown_pdf`, `send_*`) are module-level
so tests inject mocks. READ-ONLY: dispatch only ever runs research/intel agents.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from daily_brief import _reports_root, today_str
from dispatch.intent import Intent


def _public_host() -> str:
    return os.getenv("MESH_PUBLIC_HOST", "").strip() or "localhost:3000"


# ── injectable effects ───────────────────────────────────────────────────────
async def run_agent(agent_id: str, prompt: str) -> str:
    """Run an agent via the persistent tmux pool and return its markdown output."""
    from agents.runner_v2 import run_agent_task

    result = await run_agent_task(agent_id, prompt)
    return getattr(result, "output", None) or ""


def render_markdown_pdf(markdown: str, out_path: Path) -> Path:
    """Render markdown → PDF using the existing WeasyPrint pipeline."""
    from markdown_it import MarkdownIt
    from weasyprint import HTML

    html_body = MarkdownIt().render(markdown)
    html = f"<html><head><meta charset='utf-8'></head><body>{html_body}</body></html>"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html).write_pdf(str(out_path))
    return out_path


def send_telegram_message(chat_id: int, text: str) -> None:
    from integrations.base import http_post_json

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return
    http_post_json(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "MarkdownV2",
            "disable_web_page_preview": True,
        },
    )


def send_telegram_document(chat_id: int, file_path: Path, caption: str) -> None:
    # Document upload is multipart; in the live deploy this uses sendDocument.
    # Kept as a separate effect so tests assert it was called without uploading.
    import httpx

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return
    with open(file_path, "rb") as fh:
        httpx.post(
            f"https://api.telegram.org/bot{token}/sendDocument",
            data={"chat_id": chat_id, "caption": caption},
            files={"document": fh},
            timeout=30,
        )


# ── artifact metadata sidecar ────────────────────────────────────────────────
def _meta_dir(day: str) -> Path:
    # A dot-dir inside the day folder so list_artifacts (files only) ignores it.
    return _reports_root() / day / ".telegram-meta"


def write_artifact_meta(day: str, name: str, meta: dict) -> Path:
    d = _meta_dir(day)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{name}.json"
    p.write_text(json.dumps(meta, indent=2))
    return p


def read_artifact_meta(day: str, name: str) -> Optional[dict]:
    p = _meta_dir(day) / f"{name}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


# ── main entry ───────────────────────────────────────────────────────────────
async def dispatch_intent(intent: Intent, chat_id: int, requested_at: Optional[str] = None) -> dict:
    """Run the dispatch end-to-end. Returns a summary dict (also used by tests)."""
    if not intent.dispatchable:
        raise ValueError("intent is not dispatchable (forbidden/clarify/no agent)")

    requested_at = requested_at or datetime.utcnow().isoformat()
    # Persist a job row so the run shows up in /jobs.
    job_id = _create_job(intent)
    return await _produce_and_reply(intent, chat_id, job_id, requested_at)


async def _produce_and_reply(intent: Intent, chat_id: int, job_id: int, requested_at: str) -> dict:
    """Run agent → PDF → artifact → Telegram reply for an already-created job
    row. Used by the direct path AND the background worker (which pre-creates
    the queued job, then marks it running before calling this)."""
    day = today_str()
    prompt = _build_prompt(intent)
    markdown = await run_agent(intent.agent, prompt)
    if not markdown.strip():
        markdown = f"# {intent.agent} report\n\n(No output produced.)"

    name = f"{intent.agent}-{job_id}-{day}.pdf"
    pdf_path = _reports_root() / day / name
    render_markdown_pdf(markdown, pdf_path)

    meta = {
        "source": "telegram",
        "agent": intent.agent,
        "task_type": intent.task_type,
        "requested_at": requested_at,
        "prompt": intent.raw_text,
        "job_id": job_id,
    }
    write_artifact_meta(day, name, meta)
    _complete_job(job_id, markdown)

    deep_link = f"http://{_public_host()}/artifacts?id={day}/{name}"
    # Outbound reply goes through the formatter so it's short, emoji-free, clean.
    from dispatch.telegram_format import format_dispatch_reply

    text = format_dispatch_reply(
        agent=intent.agent, markdown=markdown, deep_link=deep_link
    )
    send_telegram_message(chat_id, text)
    send_telegram_document(chat_id, pdf_path, caption=f"{intent.agent} report")

    return {
        "job_id": job_id,
        "artifact": {"date": day, "name": name, "path": f"{day}/{name}", "meta": meta},
        "deep_link": deep_link,
        "summary": _summarize(markdown),
    }


def _build_prompt(intent: Intent) -> str:
    extra = f"\nParameters: {json.dumps(intent.params)}" if intent.params else ""
    return (
        f"Telegram request (read-only intel only — never place orders, transfer funds, "
        f"send messages, or modify anything): {intent.raw_text}{extra}\n\n"
        f"Produce a complete markdown report — this becomes the attached PDF, so put the depth here. "
        f"The FIRST line must be a one-sentence plain summary suitable for a terse chat reply "
        f"(the chat reply is one short line by default; never write paragraphs in chat). No emojis."
    )


def _summarize(markdown: str) -> str:
    # First non-empty, non-heading lines, trimmed to a short Telegram preview.
    lines = [l.strip() for l in markdown.splitlines() if l.strip() and not l.lstrip().startswith("#")]
    preview = " ".join(lines[:3])
    return (preview[:280] + "…") if len(preview) > 280 else (preview or "Report ready.")


def _create_job(intent: Intent) -> int:
    from db import session_scope
    from models import Job, JobStatus

    with session_scope() as s:
        job = Job(
            agent_id=intent.agent,
            prompt=intent.raw_text,
            status=JobStatus.RUNNING,
            kind="telegram_dispatch",
            started_at=datetime.utcnow(),
        )
        s.add(job)
        s.commit()
        s.refresh(job)
        return job.id


def _complete_job(job_id: int, output: str) -> None:
    from db import session_scope
    from models import Job, JobStatus, AgentRun

    with session_scope() as s:
        job = s.get(Job, job_id)
        if job:
            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.utcnow()
            s.add(job)
        s.add(AgentRun(job_id=job_id, agent_id=(job.agent_id if job else "unknown"), output=output))
        s.commit()
