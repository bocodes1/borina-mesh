from datetime import datetime
from sqlmodel import Session, create_engine, SQLModel

from models import MorningBrief


def make_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def test_morning_brief_model():
    engine = make_engine()
    with Session(engine) as s:
        brief = MorningBrief(
            date="2026-04-09",
            summary="Test brief",
            cost_summary='{"ceo": 0.05}',
            total_runs=3,
            total_cost_usd=0.05,
        )
        s.add(brief)
        s.commit()
        s.refresh(brief)
        assert brief.id is not None
        assert brief.date == "2026-04-09"
        assert brief.summary == "Test brief"
        assert brief.total_runs == 3


def test_morning_brief_date_unique():
    import pytest
    from sqlalchemy.exc import IntegrityError

    engine = make_engine()
    with Session(engine) as s:
        s.add(MorningBrief(date="2026-04-09", summary="first"))
        s.commit()
    with Session(engine) as s:
        s.add(MorningBrief(date="2026-04-09", summary="second"))
        with pytest.raises(IntegrityError):
            s.commit()
