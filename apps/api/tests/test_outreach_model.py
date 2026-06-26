"""OutreachItem staging table (Phase 1). Auto-created by init_db's create_all —
no migration. Defaults: status='proposed', timestamps."""
from datetime import datetime

from sqlmodel import select

from db import session_scope
from models import OutreachItem


def test_outreach_item_defaults_and_persist():
    with session_scope() as s:
        item = OutreachItem(
            track="swe", company="Acme AI", contact_email="founder@acme.ai",
            subject="Internship interest", body="Hi there",
            dedup_key="founder@acme.ai|acme.ai",
        )
        s.add(item)
        s.commit()
        s.refresh(item)
        assert item.id is not None
        assert item.status == "proposed"
        assert item.send_via is None and item.sent_at is None
        assert isinstance(item.created_at, datetime)


def test_outreach_item_queryable_by_dedup_key():
    with session_scope() as s:
        s.add(OutreachItem(track="finance", company="FinCo",
                           contact_email="r@finco.com", subject="x", body="y",
                           dedup_key="r@finco.com|finco.com"))
        s.commit()
        rows = s.exec(
            select(OutreachItem).where(OutreachItem.dedup_key == "r@finco.com|finco.com")
        ).all()
        assert len(rows) == 1 and rows[0].company == "FinCo"
