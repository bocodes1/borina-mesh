"""Outreach read-only API (spec §3).

Mounted at `/outreach` (frontend: `/api/outreach/...`). The /outreach tab's data
source: pipeline counts by stage, per-company rows with status + next action, and
the week's sends/replies. STRICTLY read-only — there is NO send/write route here.
Every outbound action stays behind Bo's Telegram approval tap (apply:send). The
reply `flag` (interview/rejection) is surfaced as an unconfirmed suggestion for
Bo to glance at, never a final status. Mirrors routes/daily.py.
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from db import get_session
from models import OutreachItem, OutreachReply

router = APIRouter(prefix="/outreach", tags=["outreach"])

STAGES = ["proposed", "sent", "replied", "skipped", "failed"]


@router.get("/summary")
def outreach_summary(session: Session = Depends(get_session)):
    items = session.exec(select(OutreachItem).order_by(OutreachItem.created_at.desc())).all()
    replies = session.exec(select(OutreachReply).order_by(OutreachReply.created_at.desc())).all()

    counts = {stage: 0 for stage in STAGES}
    for it in items:
        counts[it.status] = counts.get(it.status, 0) + 1

    week_start = datetime.utcnow() - timedelta(days=7)
    sent_week = sum(1 for it in items if it.sent_at and it.sent_at >= week_start)
    replied_week = sum(1 for r in replies if r.created_at >= week_start)
    cutoff = datetime.utcnow() - timedelta(days=7)
    awaiting = sum(
        1 for it in items
        if it.status == "sent" and (it.sent_at or it.created_at) <= cutoff
        and not it.dedup_key.startswith("[followup] ")
    )

    rows = [
        {"id": it.id, "company": it.company, "track": it.track,
         "contact_email": it.contact_email, "status": it.status,
         "subject": it.subject,
         "is_followup": it.dedup_key.startswith("[followup] "),
         "created_at": it.created_at.isoformat() if it.created_at else None,
         "sent_at": it.sent_at.isoformat() if it.sent_at else None}
        for it in items
    ]
    reply_rows = [
        {"outreach_item_id": r.outreach_item_id, "from_email": r.from_email,
         "subject": r.subject, "flag": r.flag, "confirmed": r.confirmed,
         "received_at": r.received_at}
        for r in replies
    ]
    return {
        "counts": counts,
        "rows": rows,
        "replies": reply_rows,
        "week": {"sent": sent_week, "replied": replied_week, "awaiting_followup": awaiting},
    }
