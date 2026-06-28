"""Files API (Phase 3 §2) — a clean, filterable view over the real artifact
registry so the Files tab isn't parsing raw paths.

Built on top of `artifacts.list_artifacts()` (which already merges local +
Obsidian-vault reports and the telegram `.telegram-meta` sidecars). Each file is
enriched with a `type` (extension) and a `source` — which scheduled task / agent
produced it, or "uploaded" — inferred from the sidecar meta or the filename.
"""
import re
from datetime import date, timedelta

from fastapi import APIRouter, Query

from artifacts import list_artifacts

router = APIRouter(prefix="/files", tags=["files"])

# Don't ship the entire ~2,700-file registry on every request: default to the
# last week, capped at the newest `_DEFAULT_LIMIT` files.
_DEFAULT_LIMIT = 200
_DEFAULT_WINDOW_DAYS = 7

# Filename-prefix → (source label, agent) for files without a meta sidecar.
_PREFIX_SOURCES: list[tuple[str, str, str]] = [
    ("daily-brief", "schedule_daily", "schedule_daily"),
    ("daily-plan", "planner", "planner"),
    ("finance-brief", "finance", "finance"),
    ("finance", "finance", "finance"),
    ("inbox-triage", "inbox-triage", "inbox-triage"),
    ("polymarket", "polymarket-intel", "polymarket-intel"),
    ("researcher", "researcher", "researcher"),
    ("ceo", "ceo", "ceo"),
    ("trader", "trader", "trader"),
    ("scout", "ecommerce-scout", "ecommerce-scout"),
    ("adset", "adset-optimizer", "adset-optimizer"),
]


def _type_of(name: str) -> str:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return ext or "file"


def _infer_source(name: str, meta_source, meta_agent) -> tuple[str, str | None]:
    if meta_source:
        return str(meta_source), (str(meta_agent) if meta_agent else None)
    low = name.lower()
    for prefix, source, agent in _PREFIX_SOURCES:
        if low.startswith(prefix):
            return source, agent
    # generic "{agent}-{number}..." pattern
    m = re.match(r"([a-z][a-z0-9_-]*?)-\d", low)
    if m:
        return m.group(1), m.group(1)
    return "uploaded", None


def _enrich(a) -> dict:
    source, agent = _infer_source(a.name, a.source, a.agent)
    return {
        "name": a.name,
        "path": a.path,
        "date": a.date,
        "modified": a.modified,
        "size_bytes": a.size_bytes,
        "type": _type_of(a.name),
        "source": source,
        "agent": agent,
        "prompt": a.prompt,
        "job_id": a.job_id,
    }


@router.get("")
def list_files(
    source: str | None = Query(None),
    type: str | None = Query(None),
    q: str | None = Query(None),
    since: str | None = Query(
        None, description="ISO date (YYYY-MM-DD); defaults to 7 days ago"
    ),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=5000),
):
    cutoff = since or (date.today() - timedelta(days=_DEFAULT_WINDOW_DAYS)).isoformat()
    # `list_artifacts()` is the only registry scan — call it once. It's already
    # sorted newest-date-first, so window by date then cap to `limit`.
    windowed = [a for a in list_artifacts() if a.date >= cutoff][:limit]
    files = [_enrich(a) for a in windowed]

    # distinct facets for the UI filters (from the windowed, pre-filter set)
    sources = sorted({f["source"] for f in files})
    types = sorted({f["type"] for f in files})

    if source and source != "all":
        files = [f for f in files if f["source"] == source]
    if type and type != "all":
        files = [f for f in files if f["type"] == type]
    if q:
        ql = q.lower()
        files = [f for f in files if ql in f["name"].lower() or (f["prompt"] and ql in f["prompt"].lower())]

    # newest first
    files.sort(key=lambda f: (f["date"], f["modified"]), reverse=True)

    return {"files": files, "sources": sources, "types": types, "count": len(files)}
