"""Telegram webhook (spec §8b.2 + §3) — the security boundary for auto-dispatch.

Order of checks (all must pass):
1. **secret-token header** (`X-Telegram-Bot-Api-Secret-Token` == TELEGRAM_WEBHOOK_SECRET)
   — fail closed: if the secret isn't configured or doesn't match → 403.
2. **allow-list** (chat_id ∈ TELEGRAM_ALLOWED_CHAT_IDS) — fail closed: empty list
   ⇒ everything ignored. Non-allowed senders are silently dropped (200, no dispatch).
3. **intent** — forbidden actions are refused (no dispatch); low-confidence asks to
   rephrase. Only a dispatchable research/intel intent is acked + enqueued.

The webhook ENQUEUES a persisted job and returns 200 fast — it NEVER awaits the
agent run. The background worker drains the queue (concurrent, crash-safe). The
update_id keys idempotency so a retried Telegram update never double-runs.
"""
import os
import re

from fastapi import APIRouter, HTTPException, Request

from dispatch import dispatcher
from dispatch.intent import resolve_intent
from dispatch.worker import enqueue_job
from dispatch.telegram_format import format_telegram

router = APIRouter(prefix="/api/telegram", tags=["telegram"])

SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"


def _check_secret(header_value: str) -> bool:
    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    # Fail closed: no configured secret ⇒ reject everything.
    return bool(secret) and header_value == secret


def _allowed_ids() -> set[int]:
    raw = os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "").strip()
    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if part:
            try:
                ids.add(int(part))
            except ValueError:
                pass
    return ids


def _handle_plan_callback(data: str, chat_id: int) -> dict:
    """Approve/reject a planner item from a Telegram inline button. Approval here
    IS the user-initiated action that commits the calendar write (same model as
    the /daily approve button). Only reachable for an allow-listed sender."""
    from planner import approve_item, reject_item

    action, _, sid = data.partition(":")
    try:
        item_id = int(sid)
    except ValueError:
        return {"ok": True, "status": "bad_data"}
    try:
        if action == "approve":
            res = approve_item(item_id)
            msg = "Approved." if res.get("committed") else "Approved (calendar not connected)."
        elif action == "reject":
            reject_item(item_id)
            msg = "Rejected."
        else:
            return {"ok": True, "status": "unknown_action"}
    except KeyError:
        return {"ok": True, "status": "not_found"}
    dispatcher.send_telegram_message(chat_id, format_telegram(msg))
    return {"ok": True, "status": action, "item_id": item_id}


_STATUS_RE = re.compile(r"^\s*(status|agents|fleet)\s*\??\s*$", re.IGNORECASE)
_REMEMBER_RE = re.compile(r"^\s*remember\s*[:,]\s+(.+)$", re.IGNORECASE | re.DOTALL)
_RECALL_RE = re.compile(r"^\s*(?:recall|what do you know about)\s*[:,]?\s+(.+)$", re.IGNORECASE | re.DOTALL)
# "build: task" / "ship: task" / "builder: task" → self-build (this mesh).
# "build <repo>: task" → external GitHub project. repo is one token before the colon.
_BUILD_RE = re.compile(
    r"^\s*(?:build|ship|builder)(?:\s+(?P<repo>[\w.\-/]+))?\s*[:,]\s+(?P<task>.+)$",
    re.IGNORECASE | re.DOTALL,
)


def _fleet_status_text() -> str:
    """One line per agent: state + cleaned current task (Telegram 'status')."""
    from agents.base import registry
    from agent_status import get_agent_status
    from db import engine

    def _clean(p: str) -> str:
        p = re.sub(r"^\[scheduled\]\s*", "", p or "")
        return re.sub(r"\s*\b(Current time|Now):.*$", "", p).strip()

    lines = []
    running = 0
    for a in registry.list():
        info = get_agent_status(a.id, engine)
        if info.get("status") == "running":
            running += 1
            lines.append(f"{a.id}: running - {_clean(info.get('current_task'))[:60]}")
        else:
            lines.append(f"{a.id}: idle")
    out = [f"{running} running / {len(lines)} agents"] + sorted(lines)

    # Active/stuck builder jobs (autonomous code changes).
    from sqlmodel import Session, select
    from models import Job, JobStatus

    with Session(engine) as s:
        builders = s.exec(
            select(Job).where(Job.kind == "builder",
                              Job.status == JobStatus.RUNNING)
        ).all()
    for b in builders:
        state = "stuck - waiting on you" if b.qa_verdict == "stuck" else "running"
        out.append(f"builder job{b.id}: {state} - {_clean(b.prompt)[:60]}")
    return "\n".join(out)


@router.post("/webhook")
async def webhook(request: Request):
    # 1. Secret-token header — hard reject (this is the security boundary).
    if not _check_secret(request.headers.get(SECRET_HEADER, "")):
        raise HTTPException(403, "invalid or missing secret token")

    return process_update(await request.json())


def process_update(update: dict) -> dict:
    """Checks 2+3 and dispatch for ONE Telegram update. Shared by the webhook
    (after its secret check) and the getUpdates poller (whose transport is
    authenticated by the bot token instead). Fail-closed allow-list either way."""
    # Inline approve/reject callbacks (planner) — same fail-closed allow-list.
    cq = update.get("callback_query")
    if cq:
        from_id = (cq.get("from") or {}).get("id")
        if from_id is None or from_id not in _allowed_ids():
            return {"ok": True, "status": "ignored"}
        return _handle_plan_callback(cq.get("data") or "", from_id)

    update_id = update.get("update_id")
    msg = update.get("message") or update.get("edited_message") or {}
    chat = msg.get("chat", {}) or {}
    chat_id = chat.get("id")
    text = msg.get("text", "") or ""

    # 2. Allow-list — fail closed; silently drop anything not from Bo.
    if chat_id is None or chat_id not in _allowed_ids():
        print(f"[telegram] ignored update from chat_id={chat_id}")
        return {"ok": True, "status": "ignored"}

    # 2b. Voice/audio → local Whisper transcript, routed exactly like text.
    # Deliberately AFTER the allow-list: media from non-allowed senders is
    # never downloaded.
    heard = ""
    media = msg.get("voice") or msg.get("audio")
    if not text and media:
        from dispatch.voice import transcribe_telegram_media

        transcript = transcribe_telegram_media(media)
        if not transcript:
            dispatcher.send_telegram_message(
                chat_id, format_telegram("Could not transcribe that audio - try typing it.")
            )
            return {"ok": True, "status": "transcribe_failed"}
        text = transcript
        heard = f'Heard: "{transcript[:160]}". '

    # 2b1. Builder: "build: X" / "ship: X" — autonomous code change in a
    # detached worktree runner. The generic forbidden gate is deliberately not
    # applied to build texts (a code task mentioning "delete" is not a live
    # deletion); the builder ships only after independent suite verification.
    bm = _BUILD_RE.match(text)
    if bm:
        from dispatch import builder

        repo = bm.group("repo")
        job_id = builder.start_build(bm.group("task").strip(), chat_id, repo=repo)
        where = f" on {repo}" if repo else ""
        dispatcher.send_telegram_message(
            chat_id,
            format_telegram(
                f"{heard}Builder started (job {job_id}){where}. I will only ping you if "
                f"stuck - otherwise the next message is the result."
            ),
        )
        return {"ok": True, "status": "build_started", "job_id": job_id}

    # 2b3. Brain commands — the machine's Obsidian memory, answered inline.
    rm = _REMEMBER_RE.match(text)
    if rm:
        from dispatch.vault_brain import remember

        remember(rm.group(1).strip(), source="telegram")
        dispatcher.send_telegram_message(chat_id, format_telegram(f"{heard}Noted - I will remember that."))
        return {"ok": True, "status": "remembered"}
    rc = _RECALL_RE.match(text)
    if rc:
        from dispatch.vault_brain import recall

        ctx = recall(rc.group(1).strip()) or "Nothing in the brain on that yet."
        dispatcher.send_telegram_message(chat_id, format_telegram(ctx, max_lines=20))
        return {"ok": True, "status": "recalled"}

    # 2b2. Fleet status command — answered inline, nothing dispatched.
    if _STATUS_RE.match(text):
        status_text = _fleet_status_text()
        dispatcher.send_telegram_message(
            chat_id,
            format_telegram(status_text, max_lines=status_text.count("\n") + 2),
        )
        return {"ok": True, "status": "status"}

    # 2c. Thread follow-up: replying to a bot report continues that topic with
    # the same agent. Forbidden gate still applies to the follow-up text.
    reply_to = (msg.get("reply_to_message") or {}).get("message_id")
    if reply_to:
        thread = dispatcher.find_thread(chat_id, reply_to)
        if thread and thread.agent_id == "builder":
            from dispatch import builder

            return builder.handle_builder_reply(thread, text, chat_id)
        if thread:
            from dispatch.intent import detect_forbidden

            reason = detect_forbidden(text)
            if reason:
                dispatcher.send_telegram_message(
                    chat_id,
                    format_telegram(
                        f"{heard}That maps to a {reason} action - not auto-dispatchable. "
                        f"I only run read-only research and intel from Telegram."
                    ),
                )
                return {"ok": True, "status": "refused", "reason": reason}
            follow_up = f"Follow-up to your earlier report on '{thread.prompt}': {text}"
            job = enqueue_job(follow_up, thread.agent_id, update_id, chat_id)
            if job is None:
                return {"ok": True, "status": "duplicate"}
            dispatcher.send_telegram_message(
                chat_id,
                format_telegram(f"{heard}Following up with {thread.agent_id}."),
            )
            return {"ok": True, "status": "dispatched", "agent": thread.agent_id, "job_id": job.id}

    # 3. Intent.
    intent = resolve_intent(text)
    if intent.forbidden:
        dispatcher.send_telegram_message(
            chat_id,
            format_telegram(
                f"{heard}That maps to a {intent.forbidden_reason} action - not auto-dispatchable. "
                f"I only run read-only research and intel from Telegram."
            ),
        )
        return {"ok": True, "status": "refused", "reason": intent.forbidden_reason}

    if not intent.dispatchable:
        dispatcher.send_telegram_message(
            chat_id, format_telegram(f"{heard}I could not confidently route that - could you rephrase?")
        )
        return {"ok": True, "status": "clarify"}

    # Enqueue (idempotent by update_id), ack, return fast. Never await the run.
    job = enqueue_job(text, intent.agent, update_id, chat_id)
    if job is None:
        return {"ok": True, "status": "duplicate"}

    dispatcher.send_telegram_message(
        chat_id,
        format_telegram(f"{heard}On it - dispatching {intent.agent}. I will send the report when it is ready."),
    )
    return {"ok": True, "status": "dispatched", "agent": intent.agent, "job_id": job.id}
