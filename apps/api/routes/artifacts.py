"""Artifact listing + read routes."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from dataclasses import asdict

from artifacts import list_artifacts, get_artifact_path

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


@router.get("")
async def list_all():
    """List every readable artifact across all date directories."""
    return [asdict(a) for a in list_artifacts()]


@router.get("/{date}/{name}/text")
async def read_text(date: str, name: str):
    """Return the artifact's raw text content for inline rendering.

    Used by the Files tab to fetch markdown and render it via react-markdown
    without forcing a download.
    """
    try:
        path = get_artifact_path(date, name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not path.exists():
        raise HTTPException(status_code=404, detail="Artifact not found")

    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise HTTPException(
            status_code=415,
            detail=f"{type(e).__name__}: artifact is not readable as UTF-8 text",
        )
    return PlainTextResponse(content, media_type="text/markdown; charset=utf-8")


@router.get("/{date}/{name}")
async def download(date: str, name: str):
    """Download the file directly (used for non-text artifacts and 'open raw')."""
    try:
        path = get_artifact_path(date, name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not path.exists():
        raise HTTPException(status_code=404, detail="Artifact not found")

    return FileResponse(str(path), filename=name)
