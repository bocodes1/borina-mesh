"""Proactive daily operator (L2).

One parent routine with three phases — morning / midday / eod — sequenced here
(not in the scheduler). It READS (brief, plan, calendar, tasks) and PROPOSES via
approval Cards; it never writes the calendar itself. The only write path stays
`planner.approve_item`, reached when Bo taps a button.

Safety: no autonomous calendar or money writes. Operator routines stage
`PlanItem` rows (status=proposed) and send Cards — nothing more.
"""
from __future__ import annotations

import os
from typing import Optional

PHASES = ("morning", "midday", "eod")


def _chat_id() -> Optional[int]:
    raw = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    try:
        return int(raw) if raw else None
    except ValueError:
        return None


def _proposed_calendar_items(day: str) -> list[dict]:
    from planner import get_plan
    plan = get_plan(day)
    return [i for i in plan.get("items", []) if i.get("kind") == "calendar" and i.get("status") == "proposed"]


def _proposed_task_items(day: str) -> list[dict]:
    from planner import get_plan
    plan = get_plan(day)
    return [i for i in plan.get("items", []) if i.get("kind") == "task" and i.get("status") == "proposed"]


def build_morning_card(day: str):
    """An approval Card for the day's proposed calendar changes (or a plain
    summary when there are none). Reuses the foundation Card channel."""
    from dispatch.cards import Card, Action

    cal = _proposed_calendar_items(day)
    tasks = _proposed_task_items(day)
    if not cal:
        lines = [f"{len(tasks)} task(s) proposed for today."] if tasks else ["Nothing needs your sign-off."]
        return Card(headline=f"Morning plan — {day}", lines=lines)

    lines = [i.get("title", "(change)") for i in cal[:8]]
    actions = [
        Action(label="Approve all", data=f"op:approveall:{day}"),
        Action(label="Skip", data=f"op:skip:{day}"),
    ]
    return Card(
        headline=f"{len(cal)} calendar change(s) proposed — {day}",
        lines=lines,
        actions=actions,
    )


async def run_phase(phase: str, day: Optional[str] = None, *, send: bool = True):
    """Run one operator phase. Returns the Card it would send (also sent to
    Telegram when `send` and a chat id is configured). No calendar writes."""
    from planner import today_str, generate_plan_with_agent, get_plan
    from dispatch.cards import Card, send_card

    day = day or today_str()
    chat = _chat_id()

    if phase == "morning":
        # Stage the layered plan (proposals only — never writes).
        try:
            summary = await generate_plan_with_agent(day)
        except Exception as e:  # noqa: BLE001
            card = Card(headline=f"Morning plan — {day}", lines=[f"(plan generation failed: {e})"])
            if send and chat:
                send_card(chat, card)
            return card
        # Send the layered narrative (brief + threads + agenda) above the card.
        if send and chat:
            try:
                from planner import plan_narrative_text
                from dispatch.dispatcher import send_telegram_message
                from dispatch.telegram_format import format_telegram
                narrative = plan_narrative_text(day, summary)
                if narrative:
                    send_telegram_message(chat, format_telegram(narrative, max_lines=30))
            except Exception as e:  # noqa: BLE001
                print(f"[operator] morning narrative error: {e}")
        card = build_morning_card(day)

    elif phase == "midday":
        plan = get_plan(day)
        pending = [i["title"] for i in plan.get("items", []) if i.get("status") == "proposed"]
        lines = ["Midday check."]
        if pending:
            lines.append(f"{len(pending)} item(s) still awaiting your tap:")
            lines += pending[:6]
        else:
            lines.append("All proposed items handled — nice.")
        card = Card(headline=f"Midday — {day}", lines=lines)

    elif phase == "eod":
        plan = get_plan(day)
        items = plan.get("items", [])
        approved = sum(1 for i in items if i.get("status") == "approved")
        rejected = sum(1 for i in items if i.get("status") == "rejected")
        pending = sum(1 for i in items if i.get("status") == "proposed")
        # Nightly learner: refresh Bo's durable profile from today's signals.
        # Best-effort — a learner failure must never break the recap.
        learn_line = "Profile unchanged."
        try:
            from operator_brain import update_profile
            res = await update_profile(day)
            if res.get("written"):
                learn_line = f"Profile updated — {res.get('active_threads', 0)} active thread(s)."
        except Exception as e:  # noqa: BLE001
            learn_line = "Profile update skipped (learner error)."
            print(f"[operator] eod learner error: {e}")
        card = Card(
            headline=f"EOD recap — {day}",
            lines=[
                f"approved {approved} · skipped {rejected} · still pending {pending}",
                learn_line,
                "Tomorrow's plan stages in the morning.",
            ],
        )
    else:
        raise ValueError(f"unknown operator phase: {phase!r}")

    if send and chat:
        send_card(chat, card)
    return card
