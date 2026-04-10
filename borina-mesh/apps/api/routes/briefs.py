"""Morning brief API routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from db import get_session
from models import MorningBrief

router = APIRouter(prefix="/briefs", tags=["briefs"])


@router.get("")
async def list_briefs(
    limit: int = 14,
    session: Session = Depends(get_session),
):
    """List recent morning briefs, newest first."""
    briefs = session.exec(
        select(MorningBrief).order_by(MorningBrief.created_at.desc()).limit(limit)
    ).all()
    return list(briefs)


@router.get("/latest")
async def latest_brief(session: Session = Depends(get_session)):
    """Get the most recent morning brief."""
    brief = session.exec(
        select(MorningBrief).order_by(MorningBrief.created_at.desc()).limit(1)
    ).first()
    if not brief:
        raise HTTPException(status_code=404, detail="No briefs yet")
    return brief


@router.post("/generate")
async def generate_brief():
    """Manually trigger morning brief generation."""
    from db import engine
    from briefs import generate_morning_brief

    brief = await generate_morning_brief(engine)
    return brief
