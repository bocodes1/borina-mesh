"""Artifact listing + download routes."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from dataclasses import asdict

from artifacts import list_artifacts, get_artifact_path

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


@router.get("")
async def list_all():
    """List all artifacts across all date directories."""
    return [asdict(a) for a in list_artifacts()]


@router.get("/{date}/{name}")
async def download(date: str, name: str):
    """Download a specific artifact."""
    try:
        path = get_artifact_path(date, name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not path.exists():
        raise HTTPException(status_code=404, detail="Artifact not found")

    return FileResponse(str(path), filename=name)
