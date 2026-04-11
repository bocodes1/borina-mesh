"""Job statistics endpoint."""

from fastapi import APIRouter
from db import engine
from stats_helper import compute_stats

router = APIRouter(tags=["stats"])


@router.get("/jobs/stats")
async def job_stats():
    return compute_stats(engine)
