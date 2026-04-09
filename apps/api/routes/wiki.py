"""Wiki engine HTTP routes (v2)."""

import uuid
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from wiki_engine.paths import vault_root
from wiki_engine.reviewer import review_batch


router = APIRouter(tags=["wiki"])


class CandidateItem(BaseModel):
    content: str = Field(..., min_length=1)
    prompt: str = Field(default="")
    source: str = Field(default="unknown")


class ProposeBody(BaseModel):
    items: list[CandidateItem] = Field(..., min_length=1)
    source: str = Field(default="claude-code")


@router.post("/memory/propose")
async def propose_memory(body: ProposeBody):
    """Submit a batch of candidate memory items. The reviewer runs
    synchronously and returns the decision summary."""
    try:
        vault_root()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    items = []
    for candidate in body.items:
        items.append({
            "id": str(uuid.uuid4())[:12],
            "content": candidate.content,
            "prompt": candidate.prompt,
            "source": candidate.source or body.source,
        })

    summary = await review_batch(items)
    return summary


@router.get("/wiki/status")
async def wiki_status():
    """Return current engine state."""
    try:
        root = vault_root()
    except RuntimeError:
        return {"configured": False}
    return {
        "configured": True,
        "vault_root": str(root),
        "version": "v2",
    }


@router.post("/wiki/digest")
async def send_daily_digest():
    """Send today's rejection digest to Telegram."""
    from wiki_engine.digest import send_daily_digest
    count = await send_daily_digest()
    return {"sent": True, "rejections_included": count}
