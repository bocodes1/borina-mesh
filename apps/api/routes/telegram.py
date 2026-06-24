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
            if res.get("already_decided"):
                return {"ok": True, "status": "approve", "item_id": item_id, "toast": "Already done"}
            if res.get("committed"):
                msg, toast = "Added to your calendar.", "Approved ✓"
            else:
                msg, toast = "Calendar not connected — kept it pending so you can retry.", "Pending"
        elif action == "reject":
            res = reject_item(item_id)
            if isinstance(res, dict) and res.get("already_decided"):
                return {"ok": True, "status": "reject", "item_id": item_id, "toast": "Already done"}
            msg, toast = "Skipped.", "Skipped"
        else:
            return {"ok": True, "status": "unknown_action", "toast": ""}
    except KeyError:
        return {"ok": True, "status": "not_found", "toast": "Not found"}
    dispatcher.send_telegram_message(chat_id, format_telegram(msg))
    return {"ok": True, "status": action, "item_id": item_id, "toast": toast}


_STATUS_RE = re.compile(r"^\s*(status|agents|fleet)\s*\??\s*$", re.IGNORECASE)
_REMEMBER_RE = re.compile(r"^\s*remember\s*[:,]\s+(.+)$", re.IGNORECASE | re.DOTALL)
_RECALL_RE = re.compile(r"^\s*(?:recall|what do you know about)\s*[:,]?\s+(.+)$", re.IGNORECASE | re.DOTALL)
# "build: task" / "ship: task" / "builder: task" → self-build (this mesh).
# "build <repo>: task" → external GitHub project. repo is one token before the colon.
_BUILD_RE = re.compile(
    r"^\s*(?:build|ship|builder)(?:\s+(?P<repo>[\w.\-/]+))?\s*[:,]\s+(?P<task>.+)$",
    re.IGNORECASE | re.DOTALL,
)
# "goal: <long-horizon goal>" → the L3 long-runner (decompose → milestones →
# check-ins). Distinct from "mission:" (single-shot parallel fan-out).
_GOAL_RE = re.compile(r"^\s*goal\s*[:,]\s+(?P<goal>.+)$", re.IGNORECASE | re.DOTALL)


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


# ── slash commands (registered with setMyCommands so they autocomplete) ──────────
_CMD_RE = re.compile(r"^\s*/(?P<cmd>help|jobs|fleet|cancel|start)\b(?:@\w+)?\s*(?P<arg>.*)$", re.IGNORECASE | re.DOTALL)

COMMANDS = [
    {"command": "help", "description": "What Borina can do + how to talk to it"},
    {"command": "jobs", "description": "Running & recent jobs (with cancel buttons)"},
    {"command": "fleet", "description": "Agent roster and their states"},
    {"command": "cancel", "description": "Cancel a running job: /cancel <id>"},
]

_HELP_TEXT = (
    "<b>Borina — your delegatable staff.</b>\n"
    "Just talk to me normally; I route to the right agent and reply with the answer "
    "(not raw logs).\n\n"
    "<b>Commands</b>\n"
    "/jobs — running &amp; recent jobs, with cancel buttons\n"
    "/fleet — the agent roster and states\n"
    "/cancel &lt;id&gt; — stop a running job\n\n"
    "<b>Power use</b>\n"
    "• <code>trader: …</code> — address one agent directly\n"
    "• <code>mission: …</code> — decompose across agents and synthesize\n"
    "• <code>build: …</code> — autonomous code change (ships only when green)\n"
    "• <code>remember: …</code> / <code>recall: …</code> — the brain\n"
    "• reply to any report to follow up with the same agent"
)


def _age(dt) -> str:
    from datetime import datetime
    if not dt:
        return "—"
    secs = int((datetime.utcnow() - dt).total_seconds())
    if secs < 90:
        return f"{secs}s"
    if secs < 5400:
        return f"{secs // 60}m"
    return f"{secs // 3600}h"


def _jobs_card():
    from dispatch.cards import Card, Action
    from db import engine
    from models import Job, JobStatus
    from sqlmodel import Session, select

    with Session(engine) as s:
        running = s.exec(
            select(Job).where(Job.status == JobStatus.RUNNING).order_by(Job.created_at.desc())
        ).all()
        recent = s.exec(select(Job).order_by(Job.created_at.desc())).all()[:6]

    lines, actions = [], []
    for j in running[:5]:
        lines.append(f"job{j.id} {j.agent_id} · running · {_age(j.started_at or j.created_at)}")
        actions.append(Action(label=f"Cancel {j.id}", data=f"cancel:{j.id}"))
    if recent:
        lines.append("recent:")
        for j in recent:
            if j.status == JobStatus.RUNNING:
                continue
            lines.append(f"job{j.id} {j.agent_id} · {j.status.value} · {_age(j.completed_at or j.created_at)} ago")
    if not lines:
        lines = ["No jobs yet."]
    return Card(headline=f"{len(running)} running", lines=lines, actions=actions)


def _fleet_card():
    from dispatch.cards import Card, Action
    from fleet_roster import list_roster, ACTIVE, PARKED

    roster = list_roster()
    lines, actions = [], []
    for r in roster:
        tag = "" if r["state"] == ACTIVE else f" ({r['state']})"
        lines.append(f"{r['short']}{tag}")
        if r["state"] == PARKED:
            actions.append(Action(label=f"Reactivate {r['short']}", data=f"unpark:{r['id']}"))
    return Card(headline="Fleet", lines=lines or ["(empty)"], actions=actions)


def _do_cancel(job_id: int) -> str:
    import os
    import signal
    from db import engine
    from models import Job, JobStatus
    from sqlmodel import Session

    active = (JobStatus.RUNNING, JobStatus.QUEUED, JobStatus.PENDING)
    with Session(engine) as s:
        job = s.get(Job, job_id)
        if not job:
            return f"No job {job_id}."
        if job.status not in active:
            return f"job{job_id} already {job.status.value}."
        if job.worker_pid:
            try:
                os.kill(job.worker_pid, signal.SIGTERM)
            except (ProcessLookupError, OSError):
                pass
        job.status = JobStatus.CANCELLED
        s.add(job)
        s.commit()
    return f"job{job_id} cancelled."


def _handle_command(cmd: str, arg: str, chat_id: int) -> dict:
    from dispatch.cards import send_card

    cmd = cmd.lower()
    if cmd in ("help", "start"):
        dispatcher.send_telegram_message(chat_id, _HELP_TEXT)
        return {"ok": True, "status": "help"}
    if cmd == "jobs":
        send_card(chat_id, _jobs_card())
        return {"ok": True, "status": "jobs"}
    if cmd == "fleet":
        send_card(chat_id, _fleet_card())
        return {"ok": True, "status": "fleet"}
    if cmd == "cancel":
        m = re.search(r"\d+", arg or "")
        if not m:
            dispatcher.send_telegram_message(chat_id, format_telegram("Usage: /cancel <job id>"))
            return {"ok": True, "status": "cancel_usage"}
        dispatcher.send_telegram_message(chat_id, format_telegram(_do_cancel(int(m.group()))))
        return {"ok": True, "status": "cancel"}
    return {"ok": True, "status": "unknown_command"}


def _handle_callback(data: str, chat_id: int) -> dict:
    """Route an inline-button callback by its verb prefix. The plan
    approve/reject verbs keep their existing handler; cancel + unpark are new."""
    action = data.split(":", 1)[0]
    if action in ("approve", "reject"):
        return _handle_plan_callback(data, chat_id)
    if action == "cancel":
        _, _, sid = data.partition(":")
        try:
            msg = _do_cancel(int(sid))
        except ValueError:
            msg = "Bad job id."
        dispatcher.send_telegram_message(chat_id, format_telegram(msg))
        return {"ok": True, "status": "cancel", "data": data}
    if action == "unpark":
        _, _, aid = data.partition(":")
        from fleet_roster import set_state, ACTIVE
        set_state(aid, ACTIVE)
        dispatcher.send_telegram_message(chat_id, format_telegram(f"Reactivated {aid}."))
        return {"ok": True, "status": "unpark", "agent": aid}
    if action == "op":
        return _handle_operator_callback(data, chat_id)
    if action in ("park", "retire", "retireconfirm"):
        return _handle_fleet_callback(action, data, chat_id)
    if action == "goal":
        return _handle_goal_callback(data, chat_id)
    return {"ok": True, "status": "unknown_action"}


def _handle_goal_callback(data: str, chat_id: int) -> dict:
    """Goal check-in buttons: goal:cont|steer|abort:{id}. Cooperative — abort
    sets a polled flag, never a kill; steer asks for a reply with guidance."""
    from dispatch import goal as goal_mod

    parts = data.split(":")
    verb = parts[1] if len(parts) > 1 else ""
    try:
        goal_id = int(parts[2]) if len(parts) > 2 else 0
    except ValueError:
        return {"ok": True, "status": "goal_bad"}

    if verb == "abort":
        goal_mod.request_cancel(goal_id)
        dispatcher.send_telegram_message(chat_id, format_telegram(f"Goal {goal_id} will stop at the next checkpoint."))
        return {"ok": True, "status": "goal_abort", "goal_id": goal_id}
    if verb == "cont":
        goal_mod.launch_goal(goal_id)
        dispatcher.send_telegram_message(chat_id, format_telegram(f"Goal {goal_id} continuing."))
        return {"ok": True, "status": "goal_cont", "goal_id": goal_id}
    if verb == "steer":
        dispatcher.send_telegram_message(chat_id, format_telegram("Reply to this with your guidance and I'll resume."))
        return {"ok": True, "status": "goal_steer", "goal_id": goal_id}
    return {"ok": True, "status": "goal_unknown"}


def _handle_fleet_callback(action: str, data: str, chat_id: int) -> dict:
    """Fleet self-management buttons. Park is reversible; retire is NEVER
    automatic — it takes a second explicit confirmation tap."""
    from dispatch.cards import Card, Action, send_card

    _, _, aid = data.partition(":")
    if action == "park":
        from fleet.actions import park_agent
        park_agent(aid)
        send_card(chat_id, Card(headline=f"Parked {aid}", lines=["Won't run on its own."],
                                actions=[Action("Reactivate", f"unpark:{aid}")]))
        return {"ok": True, "status": "park", "agent": aid}
    if action == "retire":
        # Propose only — require an explicit confirm.
        send_card(chat_id, Card(
            headline=f"Retire {aid}?",
            lines=["This removes it from routing entirely. Confirm:"],
            actions=[Action("Yes, retire", f"retireconfirm:{aid}"), Action("Keep", f"unpark:{aid}")],
        ))
        return {"ok": True, "status": "retire_proposed", "agent": aid}
    if action == "retireconfirm":
        from fleet_roster import set_state, RETIRED
        set_state(aid, RETIRED)
        dispatcher.send_telegram_message(chat_id, format_telegram(f"Retired {aid}."))
        return {"ok": True, "status": "retired", "agent": aid}
    return {"ok": True, "status": "fleet_unknown"}


def _handle_operator_callback(data: str, chat_id: int) -> dict:
    """Daily-operator approval card: op:approveall:{day} / op:skip:{day} /
    op:edit:{item_id}. Approval here IS the user-initiated calendar write."""
    from planner import get_plan, approve_item, reject_item

    parts = data.split(":")
    verb = parts[1] if len(parts) > 1 else ""
    arg = parts[2] if len(parts) > 2 else ""

    if verb == "approveall":
        items = [i for i in get_plan(arg).get("items", [])
                 if i.get("kind") == "calendar" and i.get("status") == "proposed"]
        committed = 0
        for it in items:
            try:
                if approve_item(it["id"]).get("committed"):
                    committed += 1
            except KeyError:
                pass
        if not items:
            # Nothing to do (e.g. a repeated tap) — toast only, no chat spam.
            return {"ok": True, "status": "op_approveall", "committed": 0, "toast": "Nothing to approve"}
        if committed == len(items):
            msg, toast = f"Approved {committed} calendar change(s).", "Approved ✓"
        else:
            msg, toast = (f"Approved {committed}/{len(items)} — calendar not connected for the rest, "
                          f"still pending."), "Partly approved"
        dispatcher.send_telegram_message(chat_id, format_telegram(msg))
        return {"ok": True, "status": "op_approveall", "committed": committed, "toast": toast}

    if verb == "skip":
        items = [i for i in get_plan(arg).get("items", [])
                 if i.get("kind") == "calendar" and i.get("status") == "proposed"]
        for it in items:
            try:
                reject_item(it["id"])
            except KeyError:
                pass
        if not items:
            return {"ok": True, "status": "op_skip", "skipped": 0, "toast": "Nothing to skip"}
        dispatcher.send_telegram_message(chat_id, format_telegram(f"Skipped {len(items)} change(s)."))
        return {"ok": True, "status": "op_skip", "skipped": len(items), "toast": "Skipped"}

    if verb == "edit":
        from dispatch.cards import Card, Action, send_card
        try:
            item_id = int(arg)
        except ValueError:
            return {"ok": True, "status": "op_edit_bad"}
        send_card(chat_id, Card(
            headline=f"Item {item_id}",
            lines=["Approve or reject this one:"],
            actions=[Action("Approve", f"approve:{item_id}"), Action("Reject", f"reject:{item_id}")],
        ))
        return {"ok": True, "status": "op_edit", "item_id": item_id}

    return {"ok": True, "status": "op_unknown"}


def _run_converse(text: str, chat_id: int, heard: str = "") -> None:
    """Background worker for the conversational lane: quick reply + optional
    calendar approval card. Errors degrade to a friendly line, never a stack trace."""
    from dispatch import converse as cv
    try:
        if heard:
            dispatcher.send_telegram_message(chat_id, format_telegram(heard.strip()))
        cv.handle_converse(text, chat_id)
    except Exception:  # noqa: BLE001
        dispatcher.send_telegram_message(chat_id, format_telegram("Hmm, hiccuped on that one — try again?"))


def set_my_commands() -> bool:
    """Register slash commands with Telegram so they autocomplete in the client."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return False
    try:
        from integrations.base import http_post_json
        http_post_json(
            f"https://api.telegram.org/bot{token}/setMyCommands",
            json={"commands": COMMANDS},
        )
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[telegram] setMyCommands failed: {e}")
        return False


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
        res = _handle_callback(cq.get("data") or "", from_id)
        # Always ack the tap (stops the spinner) + show a small toast instead of
        # spamming the chat with a message on every press.
        dispatcher.answer_callback_query(cq.get("id"), res.get("toast", ""))
        return res

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

    # Log the inbound message (post allow-list) for the nightly learner. Fail-open:
    # done here so voice transcripts are captured too, and only for allowed senders.
    if text:
        try:
            from conversation_log import log_message
            log_message(chat_id, "user", text)
        except Exception:  # noqa: BLE001
            pass

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

    # 2b1b. Goal: long-horizon runner — decompose → milestones → check-ins.
    gm = _GOAL_RE.match(text)
    if gm:
        from dispatch import goal as goal_mod
        goal_id = goal_mod.create_goal(gm.group("goal").strip(), chat_id)
        sent_id = dispatcher.send_telegram_message(
            chat_id,
            format_telegram(f"{heard}Goal {goal_id} started — I'll check in after each milestone. "
                            f"Reply to a check-in to steer, or tap Abort."),
        )
        # Anchor the goal thread by goal id so replies steer it.
        dispatcher._record_thread(chat_id, sent_id, "goal", goal_id, gm.group("goal").strip())
        goal_mod.launch_goal(goal_id)
        return {"ok": True, "status": "goal_started", "goal_id": goal_id}

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

    # 2b0. Slash commands (/help, /jobs, /fleet, /cancel) — answered inline.
    cmd = _CMD_RE.match(text)
    if cmd:
        return _handle_command(cmd.group("cmd"), cmd.group("arg"), chat_id)

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
        if thread and thread.agent_id == "goal":
            from dispatch import goal as goal_mod

            return goal_mod.handle_goal_reply(thread, text, chat_id)
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

    # Conversational lane: a casual message that no specialist claimed gets a
    # quick LLM reply (+ an approval card if it mentions a calendar event) —
    # NOT the heavy "dispatching researcher → report" ceremony. Run in a daemon
    # thread so the slow claude call never blocks the poller.
    if intent.source == "fallback":
        import threading
        threading.Thread(target=_run_converse, args=(text, chat_id, heard), daemon=True).start()
        return {"ok": True, "status": "converse_started"}

    # Enqueue (idempotent by update_id), ack, return fast. Never await the run.
    job = enqueue_job(text, intent.agent, update_id, chat_id)
    if job is None:
        return {"ok": True, "status": "duplicate"}

    dispatcher.send_telegram_message(
        chat_id,
        format_telegram(f"{heard}On it - dispatching {intent.agent}. I will send the report when it is ready."),
    )
    return {"ok": True, "status": "dispatched", "agent": intent.agent, "job_id": job.id}
