"""Stub: route module referenced by main.py but not yet implemented in this branch.

Added by the tmux-supervisor refactor solely to make main.py importable so the
new /api/sessions endpoints can be exercised. Replace with the real router when
the briefs feature lands.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/briefs", tags=["briefs"])
