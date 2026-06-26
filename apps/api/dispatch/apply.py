"""Cold-email pipeline (spec §1) — discover → enrich → draft → STAGE.

SAFETY — the whole point: `run_apply` NEVER sends. It only creates OutreachItem
rows (status='proposed'). The single send path is `approve_send`, which calls
integrations.outlook.send_mail(user_initiated=True) and is only ever invoked by
Bo's Telegram approval tap (mirrors planner.generate_plan / approve_item). `skip`
commits nothing. Dropped candidates (no confident email, over cap, deduped) are
counted + reasoned in the summary — never silently lost.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from sqlmodel import select

from db import session_scope
from models import OutreachItem, PostingApplication, OutreachReply

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


# ── Phase 2: job-board postings ──────────────────────────────────────────────

def _posting_dedup_key(company: str, role_title: str) -> str:
    return f"{(company or '').strip().lower()}|{(role_title or '').strip().lower()}"


async def prepare_posting(posting: dict) -> dict:
    """Have the applier agent tailor a cover letter + common-question answers for
    one posting. Text-only — never submits. Falls back to a deterministic draft if
    the agent CLI yields nothing (hermetic tests stub this entirely)."""
    from agents.runner_v2 import run_agent_task

    prompt = (
        f"Prepare an internship application.\n"
        f"Company: {posting['company']}\nRole: {posting['role_title']}\n"
        f"Location: {posting.get('location')}\nTrack: {posting['track']}\n"
        f"Posting: {posting.get('posting_url')}\n"
        f"Write a short, specific cover letter (reference the company's actual AI "
        f"work, tie it to Bo's profile, name the track), then answer the common "
        f"question 'Why do you want to work here?'. Output the cover letter first, "
        f"then a line 'WHY: ' with the answer."
    )
    result = await run_agent_task("applier", prompt)
    text = (getattr(result, "output", "") or "").strip()
    cover = text
    why = ""
    for line in text.splitlines():
        if line.upper().startswith("WHY:"):
            why = line.split(":", 1)[1].strip()
            cover = text.split(line, 1)[0].strip()
            break
    if not cover:
        cover = (f"Dear {posting['company']} team, I'm Bo — a business student "
                 f"focused on {posting['track']} + AI. I'm excited by your work and "
                 f"would love to intern on {posting['role_title']}.")
    if not why:
        why = f"I admire {posting['company']}'s AI work and want to contribute as an intern."
    return {"cover_letter": cover, "answers": {"why": why}}


async def run_postings(criteria: str = "", chat_id: Optional[int] = None) -> dict:
    """Discover postings → prepare cover/answers → STAGE. Never submits. Dropped
    (deduped) postings are counted + reasoned. Returns a batch summary."""
    from dispatch.postings import discover_postings

    found = discover_postings(criteria)
    with session_scope() as s:
        existing = {r.dedup_key for r in s.exec(select(PostingApplication)).all()}

    item_ids: list[int] = []
    dropped = 0
    reasons: list[str] = []

    for post in found:
        key = _posting_dedup_key(post["company"], post["role_title"])
        if key in existing:
            dropped += 1
            reasons.append(f"{post['company']} {post['role_title']}: dedup (already staged)")
            continue
        prep = await prepare_posting(post)
        with session_scope() as s:
            # Persist the apply_email recipient (if any) under a reserved
            # answers_json key so the submit step has it without a new column.
            answers = dict(prep["answers"])
            if post.get("apply_email"):
                answers["_apply_email"] = post["apply_email"]
            item = PostingApplication(
                track=post["track"], source=post["source"], company=post["company"],
                role_title=post["role_title"], location=post.get("location"),
                posting_url=post["posting_url"], submit_method=post["submit_method"],
                ats=post.get("ats"), cover_letter=prep["cover_letter"],
                answers_json=json.dumps(answers), dedup_key=key,
            )
            s.add(item)
            s.commit()
            s.refresh(item)
            item_ids.append(item.id)
        existing.add(key)

    return {"staged": len(item_ids), "dropped": dropped,
            "item_ids": item_ids, "reasons": reasons}


def get_proposed_postings() -> list[dict]:
    with session_scope() as s:
        rows = s.exec(
            select(PostingApplication).where(PostingApplication.status == "proposed")
            .order_by(PostingApplication.created_at)
        ).all()
        return [
            {"id": r.id, "track": r.track, "source": r.source, "company": r.company,
             "role_title": r.role_title, "location": r.location,
             "posting_url": r.posting_url, "submit_method": r.submit_method,
             "ats": r.ats, "cover_letter": r.cover_letter}
            for r in rows
        ]


def submit_posting(item_id: int) -> dict:
    """The ONLY submit path — invoked solely by Bo's Telegram approval tap.

    email   → outlook.send_mail(user_initiated=True); status 'submitted'.
    form    → BrowserFiller fills then STOPS before submit; status 'prepared',
              returns a review_url so Bo opens it and clicks submit himself.
    external→ no auto-fill; returns a handoff (deep link + prepared text);
              status 'prepared'.
    Idempotent: a non-proposed item is a no-op. A failed act stays 'failed'
    (retryable), never silently lost."""
    from integrations import outlook

    with session_scope() as s:
        item = s.get(PostingApplication, item_id)
        if not item:
            raise KeyError("posting application not found")
        if item.status != "proposed":
            return {"status": item.status, "already_decided": True}

        answers = json.loads(item.answers_json or "{}")
        try:
            if item.submit_method == "email":
                recipient = answers.get("_apply_email")
                if not recipient:
                    item.status = "failed"
                    item.error = "no apply email on posting"
                    s.add(item)
                    s.commit()
                    return {"status": "failed", "error": item.error}
                res = outlook.send_mail(
                    [recipient], f"Application — {item.role_title} ({item.company})",
                    item.cover_letter or "", user_initiated=True,
                )
                if res.connected:
                    item.status = "submitted"
                    item.submitted_at = datetime.utcnow()
                    item.error = None
                    s.add(item)
                    s.commit()
                    return {"status": "submitted", "method": "email", "company": item.company}
                item.status = "failed"
                item.error = res.error
                s.add(item)
                s.commit()
                return {"status": "failed", "error": item.error}

            if item.submit_method == "form":
                fields = {"cover_letter": item.cover_letter or "", **{
                    k: v for k, v in answers.items() if not k.startswith("_")}}
                filled = outlook.BrowserFiller().fill(item.posting_url, fields)
                # fill STOPS before submit → status 'prepared', Bo submits.
                item.status = "prepared"
                item.error = None
                s.add(item)
                s.commit()
                return {"status": "prepared", "method": "form",
                        "review_url": filled.get("review_url", item.posting_url)}

            # external (Workday / captcha / SSO) — no auto-fill, hand off.
            item.status = "prepared"
            item.error = None
            s.add(item)
            s.commit()
            return {"status": "prepared", "method": "external", "handoff": {
                "posting_url": item.posting_url,
                "cover_letter": item.cover_letter,
                "answers": {k: v for k, v in answers.items() if not k.startswith("_")},
            }}
        except Exception as exc:  # noqa: BLE001 — fail-closed, retryable
            item.status = "failed"
            item.error = f"{type(exc).__name__}: {exc}"
            s.add(item)
            s.commit()
            return {"status": "failed", "error": item.error}


def skip_posting(item_id: int) -> dict:
    """Mark a staged posting skipped. Submits/sends nothing."""
    with session_scope() as s:
        item = s.get(PostingApplication, item_id)
        if not item:
            raise KeyError("posting application not found")
        if item.status == "proposed":
            item.status = "skipped"
            s.add(item)
            s.commit()
        return {"status": item.status}


# ── Phase 3: reply detection (READ-ONLY — never sends) ───────────────────────

INTERVIEW_PHRASES = (
    "interview", "schedule a call", "set up a call", "hop on a call",
    "are you free", "chat about", "next steps", "phone screen",
)
REJECTION_PHRASES = (
    "won't be moving forward", "wont be moving forward", "not moving forward",
    "decided not to", "unable to offer", "no longer considering",
    "filled the position", "unfortunately",
)


def _classify_reply(subject: str, preview: str) -> str:
    """Suggest a flag from reply language. interview/rejection are *suggestions*
    for Bo to confirm — the caller never finalizes a status automatically."""
    blob = f"{subject}\n{preview}".lower()
    if any(p in blob for p in INTERVIEW_PHRASES):
        return "interview"
    if any(p in blob for p in REJECTION_PHRASES):
        return "rejection"
    return "neutral"


def match_replies(since_iso: Optional[str] = None) -> dict:
    """READ-ONLY reply detection (spec §3). Read the inbox, match inbound mail to
    a sent OutreachItem by recipient email, record an OutreachReply (deduped by
    graph_message_id), and advance the item to 'replied'. The interview/rejection
    flag stays UNCONFIRMED — never auto-final. NEVER sends anything."""
    from integrations import outlook

    inbox = outlook.list_inbox(since_iso=since_iso)
    if not inbox.connected:
        return {"matched": 0, "replied_item_ids": [], "flags": {}, "reasons": [inbox.error or "inbox unavailable"]}

    matched = 0
    replied_item_ids: list[int] = []
    flags: dict[int, str] = {}
    reasons: list[str] = []

    with session_scope() as s:
        # sent (or already-replied) items, keyed by lower-cased recipient
        sent = s.exec(
            select(OutreachItem).where(OutreachItem.status.in_(("sent", "replied")))
        ).all()
        by_email = {(it.contact_email or "").strip().lower(): it for it in sent}
        seen_ids = {r.graph_message_id for r in s.exec(select(OutreachReply)).all()}

        for msg in inbox.data or []:
            gid = msg.get("id", "")
            sender = (msg.get("from") or "").strip().lower()
            item = by_email.get(sender)
            if not item or not gid or gid in seen_ids:
                continue
            flag = _classify_reply(msg.get("subject", ""), msg.get("preview", ""))
            s.add(OutreachReply(
                outreach_item_id=item.id, from_email=sender,
                subject=msg.get("subject", ""), preview=msg.get("preview", ""),
                graph_message_id=gid, flag=flag, received_at=msg.get("received"),
            ))
            if item.status != "replied":
                item.status = "replied"
                s.add(item)
            seen_ids.add(gid)
            matched += 1
            replied_item_ids.append(item.id)
            flags[item.id] = flag
        s.commit()

    return {"matched": matched, "replied_item_ids": replied_item_ids,
            "flags": flags, "reasons": reasons}
