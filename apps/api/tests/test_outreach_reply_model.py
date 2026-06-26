"""OutreachReply staging table (Phase 3). Auto-created by init_db's create_all —
no migration, no ALTER of Phase 1's OutreachItem. A reply is recorded with a
classification FLAG that stays unconfirmed (confirmed=False) until Bo glances —
never auto-finalized."""
from datetime import datetime

from sqlmodel import select

from db import session_scope
from models import OutreachItem, OutreachReply


def test_outreach_reply_defaults_and_persist():
    with session_scope() as s:
        item = OutreachItem(track="swe", company="Acme AI",
                            contact_email="ada@acme.ai", subject="S", body="B",
                            dedup_key="ada@acme.ai|acme.ai", status="sent")
        s.add(item)
        s.commit()
        s.refresh(item)
        reply = OutreachReply(
            outreach_item_id=item.id, from_email="ada@acme.ai",
            subject="Re: internship", graph_message_id="m1",
        )
        s.add(reply)
        s.commit()
        s.refresh(reply)
        assert reply.id is not None
        assert reply.flag == "neutral"
        assert reply.confirmed is False         # never auto-final
        assert isinstance(reply.created_at, datetime)


def test_outreach_reply_queryable_by_graph_message_id():
    with session_scope() as s:
        s.add(OutreachReply(outreach_item_id=1, from_email="r@finco.com",
                           subject="x", graph_message_id="g-77", flag="interview"))
        s.commit()
        rows = s.exec(
            select(OutreachReply).where(OutreachReply.graph_message_id == "g-77")
        ).all()
        assert len(rows) == 1 and rows[0].flag == "interview"
