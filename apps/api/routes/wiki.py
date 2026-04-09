"""Wiki engine HTTP routes."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from wiki_engine.queue import enqueue_proposal, list_pending
from wiki_engine.paths import vault_root


router = APIRouter(tags=["wiki"])


class ProposalIn(BaseModel):
    source: str = Field(..., min_length=1)
    agent_id: str = Field(..., min_length=1)
    prompt: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)


@router.post("/memory/propose")
async def propose_memory(body: ProposalIn):
    """Submit a proposal to be reviewed. Returns queued id."""
    try:
        pid = enqueue_proposal(
            source=body.source,
            agent_id=body.agent_id,
            prompt=body.prompt,
            content=body.content,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return {"id": pid, "queued": True}


@router.get("/wiki/status")
async def wiki_status():
    """Return current engine state."""
    try:
        root = vault_root()
    except RuntimeError:
        return {"vault_root": None, "pending_count": 0, "configured": False}

    pending = list_pending()
    return {
        "configured": True,
        "vault_root": str(root),
        "pending_count": len(pending),
        "pending_sample": [
            {"id": p.id, "source": p.source, "agent_id": p.agent_id}
            for p in pending[:5]
        ],
    }


@router.post("/wiki/review")
async def trigger_review(max_items: int = 20):
    """Manually trigger a batch review run."""
    from wiki_engine.reviewer import process_pending
    summary = await process_pending(max_items=max_items)
    return summary
