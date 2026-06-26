"""Cold-email pipeline (spec §1) — discover → enrich → draft → STAGE.

SAFETY — the whole point: `run_apply` NEVER sends. It only creates OutreachItem
rows (status='proposed'). The single send path is `approve_send`, which calls
integrations.outlook.send_mail(user_initiated=True) and is only ever invoked by
Bo's Telegram approval tap (mirrors planner.generate_plan / approve_item). `skip`
commits nothing. Dropped candidates (no confident email, over cap, deduped) are
counted + reasoned in the summary — never silently lost.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import select

from db import session_scope
from models import OutreachItem

BATCH_CAP = 8
DAILY_SEND_CAP = 10
DEFAULT_TRACKS = ("swe", "finance")


def _dedup_key(email: str, domain: Optional[str]) -> str:
    return f"{(email or '').strip().lower()}|{(domain or '').strip().lower()}"


def discover(criteria: str = "") -> list[dict]:
    """Candidate AI startups per track (Toronto/remote). Returns
    [{company, domain, why_fit, track}]. Deterministic seed list for now; the
    live web-research variant slots in here later without changing callers."""
    seed = [
        {"company": "Cohere", "domain": "cohere.com", "why_fit": "Toronto LLM lab", "track": "swe"},
        {"company": "Waabi", "domain": "waabi.ai", "why_fit": "Toronto self-driving AI", "track": "swe"},
        {"company": "Borealis AI", "domain": "borealisai.com", "why_fit": "AI in finance research", "track": "finance"},
        {"company": "Wealthsimple", "domain": "wealthsimple.com", "why_fit": "fintech, AI features", "track": "finance"},
    ]
    return seed[:BATCH_CAP]


async def draft_email(candidate: dict, contact: dict) -> dict:
    """Have the applier agent draft a subject + body for one target. Returns
    {subject, body}. Text-only — no send. Falls back to a deterministic draft if
    the agent CLI yields nothing (hermetic tests stub this entirely)."""
    from agents.runner_v2 import run_agent_task

    prompt = (
        f"Draft a cold internship email.\n"
        f"Company: {candidate['company']}\nDomain: {candidate.get('domain')}\n"
        f"Why it fits Bo: {candidate.get('why_fit')}\nTrack: {candidate['track']}\n"
        f"Contact: {contact.get('name') or 'hiring team'} <{contact['email']}>\n"
        f"Output the subject on the first line prefixed 'Subject: ', then the body."
    )
    result = await run_agent_task("applier", prompt)
    text = getattr(result, "output", "") or ""
    subject = f"Internship interest — {candidate['company']}"
    body = text.strip()
    for line in text.splitlines():
        if line.lower().startswith("subject:"):
            subject = line.split(":", 1)[1].strip() or subject
            body = text.split(line, 1)[1].strip()
            break
    if not body:
        body = (f"Hi {contact.get('name') or 'there'}, I'm Bo — a business student "
                f"focused on {candidate['track']} + AI. I admire {candidate['company']}'s "
                f"work ({candidate.get('why_fit')}). Are you taking interns?")
    return {"subject": subject, "body": body}


async def run_apply(criteria: str = "", chat_id: Optional[int] = None) -> dict:
    """Discover → enrich → draft → STAGE. Never sends. Drops (no confident email,
    deduped) are counted + reasoned. Returns a batch summary."""
    from integrations import contacts

    candidates = discover(criteria)
    with session_scope() as s:
        existing = {r.dedup_key for r in s.exec(select(OutreachItem)).all()}

    item_ids: list[int] = []
    dropped = 0
    reasons: list[str] = []

    for cand in candidates:
        enr = contacts.find_contact(cand["company"], cand.get("domain", ""))
        if not enr.connected:
            dropped += 1
            reasons.append(f"{cand['company']}: {enr.error}")
            continue
        contact = enr.data
        key = _dedup_key(contact["email"], contact.get("domain"))
        if key in existing:
            dropped += 1
            reasons.append(f"{cand['company']}: dedup (already staged/sent)")
            continue
        draft = await draft_email(cand, contact)
        with session_scope() as s:
            item = OutreachItem(
                track=cand["track"], company=cand["company"],
                company_domain=cand.get("domain"), contact_name=contact.get("name"),
                contact_email=contact["email"], subject=draft["subject"],
                body=draft["body"], dedup_key=key,
            )
            s.add(item)
            s.commit()
            s.refresh(item)
            item_ids.append(item.id)
        existing.add(key)

    return {"staged": len(item_ids), "dropped": dropped,
            "item_ids": item_ids, "reasons": reasons}


def get_proposed() -> list[dict]:
    with session_scope() as s:
        rows = s.exec(
            select(OutreachItem).where(OutreachItem.status == "proposed")
            .order_by(OutreachItem.created_at)
        ).all()
        return [
            {"id": r.id, "track": r.track, "company": r.company,
             "contact_name": r.contact_name, "contact_email": r.contact_email,
             "subject": r.subject, "body": r.body}
            for r in rows
        ]


def approve_send(item_id: int) -> dict:
    """The ONLY send path. Calls outlook.send_mail(user_initiated=True) — this is
    invoked solely by Bo's Telegram approval tap. Idempotent: a non-proposed item
    is a no-op. A failed send stays 'failed' (retryable), never silently lost."""
    from integrations import outlook

    with session_scope() as s:
        item = s.get(OutreachItem, item_id)
        if not item:
            raise KeyError("outreach item not found")
        if item.status != "proposed":
            return {"status": item.status, "already_decided": True}

        res = outlook.send_mail(
            [item.contact_email], item.subject, item.body, user_initiated=True
        )
        if res.connected:
            item.status = "sent"
            item.send_via = (res.data or {}).get("via")
            item.sent_at = datetime.utcnow()
            item.error = None
        else:
            item.status = "failed"
            item.error = res.error
        s.add(item)
        s.commit()
        return {"status": item.status, "company": item.company, "error": item.error}


def skip_item(item_id: int) -> dict:
    """Mark a staged item skipped. Sends nothing."""
    with session_scope() as s:
        item = s.get(OutreachItem, item_id)
        if not item:
            raise KeyError("outreach item not found")
        if item.status == "proposed":
            item.status = "skipped"
            s.add(item)
            s.commit()
        return {"status": item.status}
