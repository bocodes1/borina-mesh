"""Goal long-runner (L3) — hand it a goal, it grinds with milestone check-ins.

A goal decomposes into milestones (durable DB rows), then a driver works them in
order. After each milestone it emits a check-in Card with [Continue]/[Steer]/
[Abort]. Steering is COOPERATIVE: a polled `cancel_requested` flag and a
GUIDANCE inbox, drained at milestone boundaries — never a blocking kill. State
lives in the DB, so a restart resumes from `cursor` without redoing done work.

The per-milestone execution is injected (`run`) so it's unit-testable without
spawning a real agent; the default runner uses the read-only researcher/ceo via
the answer pipeline (clean output, no CLI dumps).
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Awaitable, Callable, Optional

from db import session_scope
from models import Goal, Milestone, Job, JobStatus

DECOMPOSE_PROMPT = """Break this goal into 2-6 concrete, ordered milestones — each a single
self-contained step. Return ONLY a JSON array of short milestone titles, e.g.
["Research X", "Draft Y", "Verify Z"].

Goal: {goal}"""

GUIDANCE_HEADER = "## Guidance from Bo"


# ── decomposition ──────────────────────────────────────────────────────────────
def parse_milestones(text: str) -> Optional[list[str]]:
    m = re.search(r"\[.*\]", text or "", re.DOTALL)
    if not m:
        return None
    try:
        raw = json.loads(m.group(0))
    except json.JSONDecodeError:
        try:
            raw = json.loads(re.sub(r"\n\s*", " ", m.group(0)))
        except json.JSONDecodeError:
            return None
    titles = [str(x).strip() for x in raw if str(x).strip()]
    return titles or None


async def decompose_goal(text: str, run: Callable[[str], Awaitable[str]]) -> list[str]:
    """CEO-style decompose → milestone titles. Degrades to a single milestone."""
    try:
        out = await run(DECOMPOSE_PROMPT.format(goal=text))
        titles = parse_milestones(out)
        if titles:
            return titles[:6]
    except Exception:  # noqa: BLE001
        pass
    return [text.strip()[:120] or "Work the goal"]


# ── persistence helpers ──────────────────────────────────────────────────────
def create_goal(text: str, chat_id: Optional[int]) -> int:
    with session_scope() as s:
        job = Job(agent_id="goal", prompt=text, status=JobStatus.RUNNING,
                  kind="goal", started_at=datetime.utcnow(), telegram_chat_id=chat_id)
        s.add(job)
        s.commit()
        s.refresh(job)
        goal = Goal(job_id=job.id, text=text, status="planning", chat_id=chat_id)
        s.add(goal)
        s.commit()
        s.refresh(goal)
        return goal.id


def set_milestones(goal_id: int, titles: list[str]) -> None:
    with session_scope() as s:
        for i, t in enumerate(titles):
            s.add(Milestone(goal_id=goal_id, seq=i, title=t))
        goal = s.get(Goal, goal_id)
        if goal:
            goal.status = "running"
            goal.updated_at = datetime.utcnow()
            s.add(goal)
        s.commit()


def get_goal(goal_id: int) -> Optional[dict]:
    with session_scope() as s:
        g = s.get(Goal, goal_id)
        if not g:
            return None
        ms = s.exec(
            __import__("sqlmodel").select(Milestone).where(Milestone.goal_id == goal_id).order_by(Milestone.seq)
        ).all()
        return {
            "id": g.id, "job_id": g.job_id, "text": g.text, "status": g.status, "cursor": g.cursor,
            "cancel_requested": g.cancel_requested, "chat_id": g.chat_id,
            "milestones": [{"seq": m.seq, "title": m.title, "status": m.status, "result": m.result} for m in ms],
        }


def request_cancel(goal_id: int) -> None:
    with session_scope() as s:
        g = s.get(Goal, goal_id)
        if g:
            g.cancel_requested = True
            g.updated_at = datetime.utcnow()
            s.add(g)
            s.commit()


def add_guidance(goal_id: int, text: str) -> None:
    """Append steering guidance to the next pending milestone and resume."""
    from sqlmodel import select
    with session_scope() as s:
        g = s.get(Goal, goal_id)
        if not g:
            return
        nxt = s.exec(
            select(Milestone).where(Milestone.goal_id == goal_id, Milestone.status == "pending")
            .order_by(Milestone.seq)
        ).first()
        if nxt:
            nxt.title = f"{nxt.title}\n[{GUIDANCE_HEADER}: {text}]"
            s.add(nxt)
        g.status = "running"
        g.cancel_requested = False
        g.updated_at = datetime.utcnow()
        s.add(g)
        s.commit()


# ── the driver (testable: per-milestone runner is injected) ─────────────────────
async def advance_goal(
    goal_id: int,
    run: Callable[[str], Awaitable[str]],
    *,
    on_checkin: Optional[Callable[[dict], None]] = None,
    max_steps: int = 100,
) -> dict:
    """Work pending milestones in order. Polls cancel_requested at each boundary;
    persists after every milestone; calls on_checkin(goal_dict) after each. Returns
    the final goal dict. Idempotent on cursor — safe to resume."""
    from dispatch.answer import clean_agent_output

    steps = 0
    while steps < max_steps:
        steps += 1
        with session_scope() as s:
            g = s.get(Goal, goal_id)
            if not g:
                return {"status": "missing"}
            if g.cancel_requested:
                g.status = "aborted"
                g.updated_at = datetime.utcnow()
                s.add(g)
                s.commit()
                break
            from sqlmodel import select
            nxt = s.exec(
                select(Milestone).where(Milestone.goal_id == goal_id, Milestone.status == "pending")
                .order_by(Milestone.seq)
            ).first()
            if nxt is None:
                g.status = "done"
                g.updated_at = datetime.utcnow()
                s.add(g)
                s.commit()
                break
            nxt.status = "active"
            nxt.started_at = datetime.utcnow()
            s.add(nxt)
            s.commit()
            ms_id, ms_title, ms_seq = nxt.id, nxt.title, nxt.seq
            goal_text = g.text

        # Execute the milestone (outside the session; may be slow).
        try:
            raw = await run(f"Goal: {goal_text}\nMilestone {ms_seq + 1}: {ms_title}\n"
                            f"Do this step and report the result concisely.")
            result = clean_agent_output(raw) if raw else ""
            status = "done"
        except Exception as e:  # noqa: BLE001
            result = f"(milestone failed: {e})"
            status = "blocked"

        with session_scope() as s:
            m = s.get(Milestone, ms_id)
            if m:
                m.status = status
                m.result = result[:2000]
                m.completed_at = datetime.utcnow()
                s.add(m)
            g = s.get(Goal, goal_id)
            if g:
                g.cursor = ms_seq + 1
                g.status = "checkin" if status == "done" else "paused"
                g.updated_at = datetime.utcnow()
                s.add(g)
            s.commit()

        if on_checkin:
            snap = get_goal(goal_id)
            if snap:
                on_checkin(snap)
        if status == "blocked":
            break

    return get_goal(goal_id) or {"status": "missing"}


def checkin_card(goal: dict):
    """Build the [Continue]/[Steer]/[Abort] check-in Card for a goal snapshot."""
    from dispatch.cards import Card, Action

    done = sum(1 for m in goal["milestones"] if m["status"] == "done")
    total = len(goal["milestones"])
    last = next((m for m in reversed(goal["milestones"]) if m["result"]), None)
    lines = [f"milestone {done}/{total}"]
    if last:
        lines.append((last["result"] or "")[:300])
    gid = goal["id"]
    return Card(
        headline=f"Goal check-in — {goal['text'][:50]}",
        lines=lines,
        actions=[Action("Continue", f"goal:cont:{gid}"),
                 Action("Steer", f"goal:steer:{gid}"),
                 Action("Abort", f"goal:abort:{gid}")],
    )


async def run_goal(goal_id: int) -> dict:
    """Decompose (if needed) then drive the goal to completion with the default
    per-milestone runner (read-only researcher via the clean answer pipeline),
    sending a check-in Card after each milestone."""
    from dispatch.answer import run_agent_for_answer

    snap = get_goal(goal_id)
    if not snap:
        return {"status": "missing"}
    job_id = snap.get("job_id") or 0

    async def runner(prompt: str) -> str:
        return await run_agent_for_answer("researcher", prompt, job_id)

    if not snap["milestones"]:
        titles = await decompose_goal(snap["text"], runner)
        set_milestones(goal_id, titles)

    def on_checkin(g: dict) -> None:
        if g.get("chat_id"):
            try:
                from dispatch.cards import send_card
                send_card(g["chat_id"], checkin_card(g))
            except Exception:  # noqa: BLE001
                pass

    return await advance_goal(goal_id, runner, on_checkin=on_checkin)


def launch_goal(goal_id: int) -> bool:
    """Schedule run_goal on the running event loop (fire-and-forget). Returns
    False if there's no loop (caller can run it directly in tests)."""
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False
    loop.create_task(run_goal(goal_id))
    return True


def handle_goal_reply(thread, text: str, chat_id: int) -> dict:
    """A reply to a goal check-in: 'abort' cancels; anything else is steering
    guidance, applied then the goal resumes."""
    from dispatch import dispatcher
    from dispatch.telegram_format import format_telegram

    goal_id = thread.job_id  # we anchor goal threads by goal id
    if (text or "").strip().lower() in {"abort", "cancel", "stop"}:
        request_cancel(goal_id)
        dispatcher.send_telegram_message(chat_id, format_telegram(f"Goal {goal_id} aborting at the next checkpoint."))
        return {"ok": True, "status": "goal_aborted", "goal_id": goal_id}
    add_guidance(goal_id, text)
    launch_goal(goal_id)
    dispatcher.send_telegram_message(chat_id, format_telegram(f"Goal {goal_id} steering noted — resuming."))
    return {"ok": True, "status": "goal_steered", "goal_id": goal_id}


def recover_goals() -> int:
    """On startup, find goals left mid-flight (running/checkin) and mark them
    paused so a Continue tap resumes from cursor. Returns count."""
    from sqlmodel import select
    with session_scope() as s:
        live = s.exec(select(Goal).where(Goal.status.in_(["running", "checkin", "planning"]))).all()
        for g in live:
            g.status = "paused"
            s.add(g)
        s.commit()
        return len(live)
