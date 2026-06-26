"""PostingApplication staging table (Phase 2). Auto-created by init_db's
create_all — no migration. Defaults: status='proposed', answers_json='{}',
timestamps. Mirrors test_outreach_model."""
from datetime import datetime

from sqlmodel import select

from db import session_scope
from models import PostingApplication


def test_posting_defaults_and_persist():
    with session_scope() as s:
        item = PostingApplication(
            track="swe", source="wellfound", company="Acme AI",
            role_title="AI Engineering Intern", posting_url="https://wellfound.com/jobs/1",
            submit_method="form", dedup_key="acme ai|ai engineering intern",
        )
        s.add(item)
        s.commit()
        s.refresh(item)
        assert item.id is not None
        assert item.status == "proposed"
        assert item.answers_json == "{}"
        assert item.cover_letter is None and item.submitted_at is None
        assert item.ats is None and item.location is None
        assert isinstance(item.created_at, datetime)


def test_posting_queryable_by_dedup_key():
    with session_scope() as s:
        s.add(PostingApplication(
            track="finance", source="yc", company="FinML",
            role_title="Quant Intern", posting_url="https://yc.example/job/2",
            submit_method="email", dedup_key="finml|quant intern"))
        s.commit()
        rows = s.exec(
            select(PostingApplication).where(
                PostingApplication.dedup_key == "finml|quant intern")
        ).all()
        assert len(rows) == 1 and rows[0].company == "FinML"
