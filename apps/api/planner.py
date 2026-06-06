"""Planner engine (Phase 3 §3): generate a staged daily proposal, and
approve/reject individual items.

SAFETY — the whole point: `generate_plan` NEVER writes the calendar. It only
creates `PlanItem` rows (status=proposed) and writes `reports/{day}/daily-plan.md`.
The single write path is `approve_item`, which runs the existing user-initiated
calendar create (for calendar items) or creates a Task (for task items) — and is
only ever invoked by Bo's explicit approve action. Reject commits nothing.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from sqlmodel import select

from db import session_scope
from models import PlanItem, Task


def today_str() -> str:
    return date.today().isoformat()


def _reports_root() -> Path:
    return Path(os.getenv("REPORTS_DIR", "./reports")).resolve()


def _plan_path(day: str) -> Path:
    return _reports_root() / day / "daily-plan.md"


def _minus_15(iso: str) -> str:
    """15-min buffer before an ISO timestamp; resilient to a trailing Z."""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return (dt - timedelta(minutes=15)).isoformat()
    except Exception:
        return iso


def _build_proposals(day: str) -> list[dict]:
    """Deterministic, real proposals from calendar + context. NEVER writes."""
    from integrations import google_calendar
    from daily_brief import sections_for

    cal = google_calendar.list_events(f"{day}T00:00:00Z", f"{day}T23:59:59Z")
    events = cal.data if cal.connected else []

    with session_scope() as s:
        open_tasks = s.exec(select(Task).where(Task.done == False)).all()  # noqa: E712
    brief = sections_for(day, ["tasks_focus"])

    proposals: list[dict] = []

    # Calendar proposals: a prep/buffer before each real meeting.
    for ev in events:
        start = ev.get("start")
        if not start:
            continue
        proposals.append({
            "kind": "calendar",
            "title": f"Prep: {ev.get('title')}",
            "rationale": f"15-min buffer before {ev.get('title')}",
            "payload": {"summary": f"Prep: {ev.get('title')}", "start": _minus_15(start), "end": start},
        })

    # Always propose one protected deep-work focus block (a reasonable proposal,
    # not fabricated data).
    proposals.append({
        "kind": "calendar",
        "title": "Focus block (deep work)",
        "rationale": "Protect a 2h deep-work block this morning",
        "payload": {"summary": "Focus block", "start": f"{day}T09:00:00", "end": f"{day}T11:00:00"},
    })

    # Task proposals: meeting prep + items derived from the brief.
    for ev in events:
        proposals.append({
            "kind": "task",
            "title": f"Prep for {ev.get('title')}",
            "rationale": "meeting on the calendar today",
            "payload": {"title": f"Prep for {ev.get('title')}", "tag": "work", "priority": "high"},
        })
    tf = brief.get("tasks_focus")
    if tf:
        for line in [l.strip("-•* ").strip() for l in tf.splitlines() if l.strip()][:3]:
            proposals.append({
                "kind": "task",
                "title": line[:80],
                "rationale": "from today's brief",
                "payload": {"title": line[:80], "tag": "borina", "priority": "medium"},
            })

    if not any(p["kind"] == "task" for p in proposals):
        proposals.append({
            "kind": "task",
            "title": "Set top 3 priorities for today",
            "rationale": "no calendar/brief context connected yet",
            "payload": {"title": "Set top 3 priorities for today", "tag": "personal", "priority": "medium"},
        })
    return proposals


def _render_plan_md(day: str, proposals: list[dict]) -> str:
    tasks = [p for p in proposals if p["kind"] == "task"]
    cals = [p for p in proposals if p["kind"] == "calendar"]
    lines = [f"# Daily plan — {day}", "", "## Tasks"]
    lines += [f"- {t['title']}" for t in tasks] or ["- (none)"]
    lines += ["", "## Proposed calendar changes (require approval)"]
    lines += [f"- {c['title']} — {c['rationale']}" for c in cals] or ["- (none)"]
    lines += ["", "_Nothing is written to the calendar until you approve each item._"]
    return "\n".join(lines) + "\n"


def generate_plan(day: Optional[str] = None) -> dict:
    """Build today's proposal. Clears prior *proposed* items for the day (keeps
    approved/rejected history), creates fresh PlanItems, writes daily-plan.md.
    Never touches the calendar."""
    day = day or today_str()

    with session_scope() as s:
        for it in s.exec(select(PlanItem).where(PlanItem.day == day, PlanItem.status == "proposed")).all():
            s.delete(it)
        s.commit()

    proposals = _build_proposals(day)

    created_ids: list[int] = []
    with session_scope() as s:
        for p in proposals:
            item = PlanItem(
                day=day, kind=p["kind"], title=p["title"],
                rationale=p.get("rationale"), payload_json=json.dumps(p["payload"]),
            )
            s.add(item)
            s.commit()
            s.refresh(item)
            created_ids.append(item.id)

    path = _plan_path(day)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render_plan_md(day, proposals))

    return {
        "day": day,
        "item_ids": created_ids,
        "task_count": sum(1 for p in proposals if p["kind"] == "task"),
        "calendar_count": sum(1 for p in proposals if p["kind"] == "calendar"),
        "path": str(path),
    }


def get_plan(day: Optional[str] = None) -> dict:
    day = day or today_str()
    with session_scope() as s:
        items = s.exec(
            select(PlanItem).where(PlanItem.day == day).order_by(PlanItem.kind, PlanItem.created_at)
        ).all()
        out = [
            {
                "id": i.id, "kind": i.kind, "status": i.status, "title": i.title,
                "rationale": i.rationale, "payload": json.loads(i.payload_json),
                "committed_ref": i.committed_ref,
            }
            for i in items
        ]
    path = _plan_path(day)
    raw = path.read_text() if path.exists() else None
    return {
        "day": day,
        "has_plan": bool(out),
        "raw": raw,
        "items": out,
        "tasks": [i for i in out if i["kind"] == "task"],
        "calendar": [i for i in out if i["kind"] == "calendar"],
    }


def approve_item(item_id: int) -> dict:
    """The ONLY write path. Calendar item → user-initiated calendar create; task
    item → create Task. Idempotent: an already-decided item is a no-op."""
    with session_scope() as s:
        item = s.get(PlanItem, item_id)
        if not item:
            raise KeyError("plan item not found")
        if item.status != "proposed":
            return {"status": item.status, "already_decided": True}

        payload = json.loads(item.payload_json)
        committed = False
        note = None

        if item.kind == "calendar":
            from integrations import google_calendar

            event = {
                "summary": payload["summary"],
                "start": {"dateTime": payload["start"]},
                "end": {"dateTime": payload["end"]},
            }
            # This IS the user-initiated action (Bo approved it).
            res = google_calendar.create_event(event, user_initiated=True)
            committed = res.connected
            note = res.error
            item.committed_ref = (res.data or {}).get("id") if res.connected else None
        else:  # task
            t = Task(
                title=payload["title"],
                tag=payload.get("tag", "personal"),
                priority=payload.get("priority", "medium"),
            )
            s.add(t)
            s.commit()
            s.refresh(t)
            item.committed_ref = str(t.id)
            committed = True

        item.status = "approved"
        item.decided_at = datetime.utcnow()
        s.add(item)
        s.commit()
        return {
            "status": "approved",
            "kind": item.kind,
            "committed": committed,
            "committed_ref": item.committed_ref,
            "note": note,
        }


def reject_item(item_id: int) -> dict:
    with session_scope() as s:
        item = s.get(PlanItem, item_id)
        if not item:
            raise KeyError("plan item not found")
        if item.status == "proposed":
            item.status = "rejected"
            item.decided_at = datetime.utcnow()
            s.add(item)
            s.commit()
        return {"status": item.status}


def plan_digest_text(day: Optional[str] = None) -> str:
    """Terse morning digest for Telegram (run through the §1 formatter by caller)."""
    plan = get_plan(day)
    proposed = [i for i in plan["items"] if i["status"] == "proposed"]
    n_task = sum(1 for i in proposed if i["kind"] == "task")
    n_cal = sum(1 for i in proposed if i["kind"] == "calendar")
    host = os.getenv("MESH_PUBLIC_HOST", "").strip() or "localhost:3000"
    return f"Plan ready: {n_task} tasks, {n_cal} proposed calendar changes. Approve in /daily. http://{host}/daily"
