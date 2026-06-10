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
import re
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


# ── live agent path (Phase 4 §2) ─────────────────────────────────────────────
# The planner agent only ever produces TEXT (a JSON proposal list) that is
# staged as PlanItem rows — the no-autonomous-write rule is untouched: the only
# write path remains approve_item, invoked by Bo.

PLANNER_TASK_PROMPT = """<task name="daily_plan">
You are Bo's chief-of-staff planner. Draft today's ({day}) plan as STAGED PROPOSALS.
You never write to the calendar or task list — you only propose; Bo approves each item.

Context:
- Calendar events today: {events}
- Open tasks: {tasks}
- Brief TL;DR: {tldr}
- Brief focus suggestions: {tasks_focus}

Propose at most 8 items: a 15-min prep buffer before each real meeting, one protected
deep-work focus block, and the 2-4 highest-leverage tasks for today. Be specific to the
context above; no generic filler.

Output ONLY a JSON array (no prose, no code fences). Each element:
  {{"kind": "task" | "calendar", "title": "...", "rationale": "...", "payload": {{...}}}}
- kind=calendar payload: {{"summary": "...", "start": "ISO-8601", "end": "ISO-8601"}}
- kind=task payload: {{"title": "...", "tag": "work|personal|borina", "priority": "high|medium|low"}}

ALSO save the exact same JSON array to proposals/{day}.json under your working
directory (create the folder if needed) — that file is the canonical handoff.
</task>"""


def _agent_proposals_file(day: str) -> Path:
    """Where the planner agent saves its JSON proposals inside its workdir.
    Reading this beats scraping the tmux pane (which wraps long JSON strings)."""
    from agents.runner_v2 import AGENT_REGISTRY, _workdir_root

    entry = AGENT_REGISTRY.get("planner", {})
    workdir = Path(entry.get("workdir") or (_workdir_root() / "planner"))
    return workdir / "proposals" / f"{day}.json"


async def _call_agent(prompt: str) -> str:
    from agents.runner_v2 import run_agent_task

    result = await run_agent_task("planner", prompt)
    return getattr(result, "output", None) or ""


def _parse_agent_proposals(text: str) -> Optional[list[dict]]:
    """Strict-ish parse of the agent's JSON proposal list. Invalid items are
    dropped; returns None unless at least one valid proposal survives."""
    if not text:
        return None
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        return None
    try:
        raw = json.loads(m.group(0))
    except Exception:
        # A tmux pane wraps long lines, leaving raw newlines inside JSON string
        # literals. Newlines between tokens are insignificant, so collapsing
        # them is structurally safe and repairs the wrapped strings.
        try:
            raw = json.loads(re.sub(r"\n\s*", " ", m.group(0)))
        except Exception:
            return None
    if not isinstance(raw, list):
        return None
    valid: list[dict] = []
    for it in raw[:12]:
        if not isinstance(it, dict):
            continue
        kind = it.get("kind")
        title = str(it.get("title") or "").strip()[:80]
        if kind not in ("task", "calendar") or not title:
            continue
        payload = it.get("payload") if isinstance(it.get("payload"), dict) else {}
        if kind == "calendar":
            if not all(
                isinstance(payload.get(k), str) and payload.get(k)
                for k in ("summary", "start", "end")
            ):
                continue
        else:
            payload = {
                "title": str(payload.get("title") or title)[:80],
                "tag": payload.get("tag", "borina"),
                "priority": payload.get("priority", "medium"),
            }
        valid.append({
            "kind": kind,
            "title": title,
            "rationale": str(it.get("rationale") or "")[:200],
            "payload": payload,
        })
    return valid[:8] or None


def _agent_context(day: str) -> dict:
    """Read-only context strings for the planner prompt."""
    from integrations import google_calendar
    from daily_brief import sections_for

    cal = google_calendar.list_events(f"{day}T00:00:00Z", f"{day}T23:59:59Z")
    events = cal.data if cal.connected else []
    with session_scope() as s:
        open_tasks = s.exec(select(Task).where(Task.done == False)).all()  # noqa: E712
    brief = sections_for(day, ["tldr", "tasks_focus"])
    return {
        "day": day,
        "events": json.dumps(
            [{"title": e.get("title"), "start": e.get("start"), "end": e.get("end")} for e in events]
        ) if events else "none connected",
        "tasks": json.dumps(
            [{"title": t.title, "tag": t.tag, "due": t.due.isoformat() if t.due else None} for t in open_tasks]
        ) if open_tasks else "none",
        "tldr": brief.get("tldr") or "no brief yet",
        "tasks_focus": brief.get("tasks_focus") or "none",
    }


async def _run_agent_proposals(day: str) -> Optional[list[dict]]:
    try:
        prompt = PLANNER_TASK_PROMPT.format(**_agent_context(day))
        output = await _call_agent(prompt)
    except Exception as exc:  # noqa: BLE001
        print(f"[planner] agent path failed, using heuristics: {exc}")
        return None
    # Preferred handoff: the file the agent wrote; pane capture as fallback.
    try:
        f = _agent_proposals_file(day)
        if f.exists():
            parsed = _parse_agent_proposals(f.read_text())
            if parsed:
                return parsed
    except Exception as exc:  # noqa: BLE001
        print(f"[planner] workdir proposals unreadable: {exc}")
    return _parse_agent_proposals(output)


def _render_plan_md(day: str, proposals: list[dict], source: str = "fallback") -> str:
    tasks = [p for p in proposals if p["kind"] == "task"]
    cals = [p for p in proposals if p["kind"] == "calendar"]
    origin = "Proposed live by the planner agent." if source == "agent" else "Proposed by fallback heuristics (no LLM)."
    lines = [f"# Daily plan — {day}", "", f"_{origin}_", "", "## Tasks"]
    lines += [f"- {t['title']}" for t in tasks] or ["- (none)"]
    lines += ["", "## Proposed calendar changes (require approval)"]
    lines += [f"- {c['title']} — {c['rationale']}" for c in cals] or ["- (none)"]
    lines += ["", "_Nothing is written to the calendar until you approve each item._"]
    return "\n".join(lines) + "\n"


def generate_plan(
    day: Optional[str] = None,
    proposals: Optional[list[dict]] = None,
    source: str = "fallback",
) -> dict:
    """Build today's proposal. Clears prior *proposed* items for the day (keeps
    approved/rejected history), creates fresh PlanItems, writes daily-plan.md.
    Never touches the calendar."""
    day = day or today_str()

    with session_scope() as s:
        for it in s.exec(select(PlanItem).where(PlanItem.day == day, PlanItem.status == "proposed")).all():
            s.delete(it)
        s.commit()

    if proposals is None:
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
    path.write_text(_render_plan_md(day, proposals, source))

    return {
        "day": day,
        "source": source,
        "item_ids": created_ids,
        "task_count": sum(1 for p in proposals if p["kind"] == "task"),
        "calendar_count": sum(1 for p in proposals if p["kind"] == "calendar"),
        "path": str(path),
    }


async def generate_plan_with_agent(day: Optional[str] = None) -> dict:
    """Live path: have the planner agent draft the proposals; fall back to the
    deterministic heuristics. Staging-only either way — no calendar writes."""
    day = day or today_str()
    agent_proposals = await _run_agent_proposals(day)
    if agent_proposals:
        return generate_plan(day, proposals=agent_proposals, source="agent")
    return generate_plan(day)


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
