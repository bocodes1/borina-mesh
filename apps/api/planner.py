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


async def _call_agent(prompt: str) -> str:
    from agents.runner_v2 import run_agent_task

    result = await run_agent_task("planner", prompt)
    return getattr(result, "output", None) or ""


# ── live agent path: layered plan ────────────────────────────────────────────
# The planner agent produces TEXT only (a JSON object) staged as PlanItem rows —
# the no-autonomous-write rule is untouched: the only write path remains
# approve_item, invoked by Bo. The agent returns {brief, threads, items}; the
# calendar `items` ARE Bo's time-blocked agenda. (Reuses _call_agent above.)

PLANNER_PLAN_PROMPT = """<task name="daily_plan">
You are Bo's chief-of-staff planner. Draft today's ({day}) plan as STAGED PROPOSALS.
You never write to the calendar or task list — you only propose; Bo approves each item.

Bo's durable profile (what he's working on + how he likes his days):
{profile}

Today's context:
- Calendar events: {events}
- Open tasks: {tasks}
- Brief TL;DR: {tldr}
- Brief focus suggestions: {tasks_focus}
- Recent Obsidian daily notes (prefer FRESH items; SKIP long-running recurring ones): {obsidian}

Produce a LAYERED plan. Output ONLY a JSON object (no prose, no code fences):
{{
  "brief": "<2-4 sentence narrative: where Bo is, what today is for>",
  "threads": [{{"name": "...", "today": "<concrete next action today>", "why": "..."}}],
  "items": [ ... ]
}}
Each element of "items":
  {{"kind": "task" | "calendar", "title": "...", "rationale": "...", "payload": {{...}}}}
- kind=calendar payload: {{"summary": "...", "start": "ISO-8601", "end": "ISO-8601"}}
- kind=task payload: {{"title": "...", "tag": "work|personal|borina", "priority": "high|medium|low"}}

The kind=calendar items ARE Bo's time-blocked agenda: lay out the working day as
calendar blocks — a 15-min prep buffer before each real meeting, protected
deep-work block(s), and a timed slot for each top task — with real start/end times
that don't overlap existing events. At most 10 items total. Ground everything in
the profile + context above; no generic filler.

ALSO save this exact JSON object to plan/{day}.json under your working directory
(create the folder if needed) — that file is the canonical handoff.
</task>"""


def _safe_profile() -> str:
    """Bo's durable profile for the prompt; never raises (empty/no-vault → note)."""
    try:
        from operator_brain import read_profile
        return read_profile()[:3000]
    except Exception:  # noqa: BLE001
        return "(no profile yet)"


def _agent_plan_file(day: str) -> Path:
    """Where the planner agent saves its JSON plan object inside its workdir."""
    from agents.runner_v2 import AGENT_REGISTRY, _workdir_root

    entry = AGENT_REGISTRY.get("planner", {})
    workdir = Path(entry.get("workdir") or (_workdir_root() / "planner"))
    return workdir / "plan" / f"{day}.json"


def _validate_items(raw_items) -> list[dict]:
    """Validate/normalize the proposal items. Drops invalid; caps at 8."""
    valid: list[dict] = []
    for it in (raw_items or [])[:12]:
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
    return valid[:8]


def _parse_agent_plan(text: str) -> Optional[dict]:
    """Parse the agent's {brief, threads, items} object. Returns None unless at
    least one valid item survives (so callers fall back to heuristics)."""
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    blob = m.group(0)
    try:
        raw = json.loads(blob)
    except Exception:
        # tmux pane wrap leaves raw newlines inside JSON string literals;
        # collapsing inter-token whitespace repairs the wrapped strings.
        try:
            raw = json.loads(re.sub(r"\n\s*", " ", blob))
        except Exception:
            return None
    if not isinstance(raw, dict):
        return None
    items = _validate_items(raw.get("items") if isinstance(raw.get("items"), list) else [])
    if not items:
        return None
    threads: list[dict] = []
    for t in (raw.get("threads") or [])[:8]:
        if isinstance(t, dict) and (t.get("name") or t.get("today")):
            threads.append({
                "name": str(t.get("name") or "")[:80],
                "today": str(t.get("today") or "")[:160],
                "why": str(t.get("why") or "")[:160],
            })
    return {"brief": str(raw.get("brief") or "")[:600], "threads": threads, "items": items}


async def _run_agent_plan(day: str) -> Optional[dict]:
    try:
        from agents.context_pack import build_context_pack
        from agents.contracts import last_artifact_text
        prompt = PLANNER_PLAN_PROMPT.format(**_agent_context(day))
        pack = build_context_pack("planner", query="daily plan calendar tasks",
                                  data="", last_artifact=last_artifact_text("planner"))
        prompt = f"{prompt}\n\nCONTEXT:\n{pack.text}"
        output = await _call_agent(prompt)
    except Exception as exc:  # noqa: BLE001
        print(f"[planner] agent path failed, using heuristics: {exc}")
        return None
    # Preferred handoff: the file the agent wrote; pane capture as fallback.
    try:
        f = _agent_plan_file(day)
        if f.exists():
            parsed = _parse_agent_plan(f.read_text())
            if parsed:
                return parsed
    except Exception as exc:  # noqa: BLE001
        print(f"[planner] workdir plan unreadable: {exc}")
    return _parse_agent_plan(output)


def _recent_daily_notes(limit: int = 2, max_chars: int = 4000) -> str:
    """Newest Obsidian daily notes — Bo's actual current work (read-only).
    Empty-vault/dev/test environments simply get no vault context."""
    root = os.getenv("OBSIDIAN_VAULT_PATH", "").strip()
    if not root:
        return ""
    daily_dir = Path(root) / "01-daily"
    if not daily_dir.is_dir():
        return ""
    chunks = []
    for note in sorted(daily_dir.glob("????-??-??.md"), reverse=True)[:limit]:
        try:
            chunks.append(f"### {note.stem}\n{note.read_text()}")
        except OSError:
            continue
    return "\n\n".join(chunks)[:max_chars]


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
        "obsidian": _recent_daily_notes() or "no vault notes",
        "profile": _safe_profile(),
    }


def _render_plan_md(day: str, proposals: list[dict], source: str = "fallback",
                    brief: str = "", threads: Optional[list[dict]] = None) -> str:
    threads = threads or []
    tasks = [p for p in proposals if p["kind"] == "task"]
    cals = [p for p in proposals if p["kind"] == "calendar"]
    origin = "Proposed live by the planner agent." if source == "agent" else "Proposed by fallback heuristics (no LLM)."
    lines = [f"# Daily plan — {day}", "", f"_{origin}_", ""]
    if brief:
        lines += ["## Brief", "", brief, ""]
    if threads:
        lines += ["## Threads", ""]
        for t in threads:
            why = f" — _{t['why']}_" if t.get("why") else ""
            lines.append(f"- **{t.get('name', '')}**: {t.get('today', '')}{why}")
        lines += [""]
    lines += ["## Agenda (proposed calendar blocks — require approval)", ""]
    lines += [f"- {c['title']} — {c['rationale']}" for c in cals] or ["- (none)"]
    lines += ["", "## Tasks", ""]
    lines += [f"- {t['title']}" for t in tasks] or ["- (none)"]
    lines += ["", "_Nothing is written to the calendar until you approve each item._"]
    return "\n".join(lines) + "\n"


def generate_plan(
    day: Optional[str] = None,
    proposals: Optional[list[dict]] = None,
    source: str = "fallback",
    brief: str = "",
    threads: Optional[list[dict]] = None,
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
    path.write_text(_render_plan_md(day, proposals, source, brief=brief, threads=threads or []))

    return {
        "day": day,
        "source": source,
        "item_ids": created_ids,
        "task_count": sum(1 for p in proposals if p["kind"] == "task"),
        "calendar_count": sum(1 for p in proposals if p["kind"] == "calendar"),
        "path": str(path),
        "brief": brief,
        "threads": threads or [],
    }


async def generate_plan_with_agent(day: Optional[str] = None) -> dict:
    """Live path: have the planner agent draft the layered plan; fall back to the
    deterministic heuristics. Staging-only either way — no calendar writes."""
    day = day or today_str()
    plan = await _run_agent_plan(day)
    if plan and plan.get("items"):
        return generate_plan(
            day, proposals=plan["items"], source="agent",
            brief=plan.get("brief", ""), threads=plan.get("threads") or [],
        )
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

            # op defaults to "create" for back-compat; move/update/delete are the
            # daily-operator ops. Approval IS the user-initiated action (Bo tapped).
            op = payload.get("op", "create")
            if op == "delete":
                res = google_calendar.delete_event(payload["event_id"], user_initiated=True)
            elif op == "move":
                res = google_calendar.move_event(
                    payload["event_id"], payload["start"], payload["end"], user_initiated=True
                )
            elif op == "update":
                changes = payload.get("changes") or {}
                res = google_calendar.update_event(payload["event_id"], changes, user_initiated=True)
            else:  # create
                event = {
                    "summary": payload["summary"],
                    "start": {"dateTime": payload["start"]},
                    "end": {"dateTime": payload["end"]},
                }
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

        # Only finalize when the write actually committed. A calendar item
        # approved while disconnected stays 'proposed' so it can be retried
        # once the calendar is connected — never silently lost.
        if committed:
            item.status = "approved"
            item.decided_at = datetime.utcnow()
            s.add(item)
            s.commit()
        return {
            "status": item.status,
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


def plan_narrative_text(day: str, summary: dict) -> str:
    """The morning Telegram narrative: brief → threads → agenda. Trimmed for chat;
    the full layered document lives in daily-plan.md."""
    brief = (summary or {}).get("brief") or ""
    threads = (summary or {}).get("threads") or []
    plan = get_plan(day)
    cals = plan.get("calendar", [])
    lines = [f"Plan for {day}"]
    if brief:
        lines += ["", brief]
    if threads:
        lines += ["", "Threads:"]
        for t in threads[:5]:
            lines.append(f"• {t.get('name', '')}: {t.get('today', '')}")
    if cals:
        lines += ["", "Agenda:"]
        for c in cals[:10]:
            lines.append(f"• {c['title']}")
    return "\n".join(lines)
