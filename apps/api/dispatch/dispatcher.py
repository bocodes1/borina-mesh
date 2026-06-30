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


def send_telegram_message(chat_id: int, text: str, reply_markup: Optional[dict] = None) -> Optional[int]:
    """Send; returns Telegram's message_id (None offline/on failure) so the
    reply can be recorded as a thread anchor. Pass `reply_markup` (an
    inline_keyboard dict) to attach buttons — used by the Card channel."""
    from integrations.base import http_post_json

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return None
    try:  # mirror Borina's side into the learner's signal (fail-open)
        from conversation_log import log_message
        log_message(chat_id, "borina", text)
    except Exception:  # noqa: BLE001
        pass
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    resp = http_post_json(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json=payload,
    )
    try:
        return int((resp.get("result") or {}).get("message_id"))
    except Exception:  # noqa: BLE001
        return None


def answer_callback_query(callback_query_id: Optional[str], text: str = "") -> None:
    """Acknowledge an inline-button tap — stops the client's loading spinner and
    shows a small toast. Lets us give feedback WITHOUT spamming the chat with a
    new message on every tap."""
    if not callback_query_id:
        return
    from integrations.base import http_post_json

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return
    try:
        http_post_json(
            f"https://api.telegram.org/bot{token}/answerCallbackQuery",
            json={"callback_query_id": callback_query_id, "text": text[:200]},
        )
    except Exception:  # noqa: BLE001
        pass


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
    """Run agent → clean answer → (opt-in PDF) → artifact → Telegram reply for an
    already-created job row. Used by the direct path AND the background worker.

    The reply carries the agent's ANSWER, never the raw tmux pane (see
    dispatch.answer). A PDF is attached ONLY when the request asked for one."""
    from dispatch import answer
    from dispatch.telegram_format import (
        format_answer_reply, format_dispatch_reply, format_telegram,
    )

    day = today_str()
    if intent.task_type == "mission":
        # Missions are now DAG Runs driven by the orchestration engine: it
        # decomposes, fans out across agents, synthesizes + verifies, and surfaces
        # the dispatch ping + final report to chat itself. Reuse this job row as
        # the Run's backing Job so there's a single /jobs entry.
        from dispatch.orchestrator.engine import run_orchestration

        snap = await run_orchestration(
            intent.raw_text, mode="mission", chat_id=chat_id, job_id=job_id
        )
        report = snap.get("report") or ""
        _complete_job(job_id, report or "(no output produced)")
        return {
            "job_id": job_id,
            "run_id": snap.get("run_id"),
            "mode": "mission",
            "status": snap.get("status"),
            "summary": _summarize(report or "Mission run."),
        }

    prompt = _build_prompt(intent)
    markdown = await answer.run_agent_for_answer(intent.agent, prompt, job_id)
    if not markdown.strip():
        markdown = "(No output produced.)"

    # Always persist a clean markdown artifact (browsable in the Files tab and
    # the deep link target) + the Obsidian brain write-back.
    md_name = f"{intent.agent}-{job_id}-{day}.md"
    md_path = _reports_root() / day / md_name
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(markdown)

    meta = {
        "source": "telegram",
        "agent": intent.agent,
        "task_type": intent.task_type,
        "requested_at": requested_at,
        "prompt": intent.raw_text,
        "job_id": job_id,
    }
    write_artifact_meta(day, md_name, meta)
    _complete_job(job_id, markdown)

    from dispatch.vault_writeback import save_dispatch_to_vault
    save_dispatch_to_vault(intent.agent, intent.raw_text, markdown, day, job_id)

    want_pdf = answer.wants_pdf(intent.raw_text)
    artifact_name = md_name
    if want_pdf:
        # Opt-in PDF: render + attach, terse chat reply pointing at it.
        artifact_name = f"{intent.agent}-{job_id}-{day}.pdf"
        pdf_path = _reports_root() / day / artifact_name
        render_markdown_pdf(markdown, pdf_path)
        write_artifact_meta(day, artifact_name, meta)
        deep_link = f"http://{_public_host()}/artifacts?id={day}/{artifact_name}"
        text = format_dispatch_reply(agent=intent.agent, markdown=markdown, deep_link=deep_link)
        sent_id = send_telegram_message(chat_id, text)
        send_telegram_document(chat_id, pdf_path, caption=f"{intent.agent} report")
    else:
        # Default: the clean answer IS the chat reply. No PDF.
        deep_link = f"http://{_public_host()}/artifacts?id={day}/{md_name}"
        text = format_answer_reply(agent=intent.agent, markdown=markdown, deep_link=deep_link)
        sent_id = send_telegram_message(chat_id, text)

    _record_thread(chat_id, sent_id, intent.agent, job_id, intent.raw_text)

    return {
        "job_id": job_id,
        "artifact": {"date": day, "name": artifact_name, "path": f"{day}/{artifact_name}", "meta": meta},
        "deep_link": deep_link,
        "summary": _summarize(markdown),
        "pdf": want_pdf,
    }


def _build_prompt(intent: Intent) -> str:
    extra = f"\nParameters: {json.dumps(intent.params)}" if intent.params else ""

    # Recall relevant context from the vault (the machine's brain) so answers
    # build on what the mesh already knows. Empty string without a vault.
    brain = ""
    try:
        from dispatch.vault_brain import recall

        brain = recall(intent.raw_text)
    except Exception:  # noqa: BLE001
        brain = ""
    brain_block = f"\n\n{brain}\n" if brain else ""

    return (
        f"Telegram request (read-only intel only — never place orders, transfer funds, "
        f"send messages, or modify anything): {intent.raw_text}{extra}{brain_block}\n\n"
        f"Answer the request directly and concisely. Lead with a one-sentence summary, "
        f"then the supporting detail. Plain prose, no emojis. If you used the brain context "
        f"above, build on it rather than repeating it."
    )


def _summarize(markdown: str) -> str:
    # First non-empty, non-heading lines, trimmed to a short Telegram preview.
    lines = [l.strip() for l in markdown.splitlines() if l.strip() and not l.lstrip().startswith("#")]
    preview = " ".join(lines[:3])
    return (preview[:280] + "…") if len(preview) > 280 else (preview or "Report ready.")


def _record_thread(chat_id: int, message_id: Optional[int], agent_id: str,
                   job_id: int, prompt: str) -> None:
    """Anchor the bot's report message so a user reply continues this topic."""
    if not message_id:
        return
    from db import session_scope
    from models import TelegramThread

    with session_scope() as s:
        s.add(TelegramThread(chat_id=chat_id, message_id=message_id,
                             agent_id=agent_id, job_id=job_id, prompt=prompt[:300]))
        s.commit()


def find_thread(chat_id: int, message_id: int):
    from db import session_scope
    from models import TelegramThread
    from sqlmodel import select

    with session_scope() as s:
        return s.exec(
            select(TelegramThread).where(
                TelegramThread.chat_id == chat_id,
                TelegramThread.message_id == message_id,
            )
        ).first()


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
