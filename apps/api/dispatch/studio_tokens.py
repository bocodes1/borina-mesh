"""Launch Studio button tokens (M5, contracts §9).

Telegram caps callback_data at 64 bytes, so a studio button carries
`st:<8 hex>` and its action lives in the StudioToken table. A tap claims its
token atomically before acting, so a double tap, or an update Telegram
re-delivers after a restart, acts once."""
from __future__ import annotations

import json
import re
import secrets
from datetime import datetime
from typing import Optional

from sqlalchemy import update
from sqlmodel import col

from db import session_scope
from models import StudioToken

PREFIX = "st:"
KINDS = ("build", "skip", "retry", "answer", "confirm", "cancel")
_TOKEN_RE = re.compile(r"^[0-9a-f]{8}$")


def mint(kind: str, payload: dict, *, slug: Optional[str] = None, stop_id: Optional[str] = None) -> str:
    if kind not in KINDS:
        raise ValueError(f"unknown studio token kind {kind!r}")
    body = json.dumps(payload, separators=(",", ":"))
    for _ in range(5):
        tok = secrets.token_hex(4)
        with session_scope() as s:
            if s.get(StudioToken, tok) is not None:
                continue
            s.add(StudioToken(token=tok, kind=kind, payload_json=body, slug=slug, stop_id=stop_id))
            s.commit()
            return PREFIX + tok
    raise RuntimeError("could not mint a unique studio token")


def _key(data: str) -> Optional[str]:
    tok = data[len(PREFIX):] if isinstance(data, str) and data.startswith(PREFIX) else ""
    return tok if _TOKEN_RE.match(tok) else None


def peek(data: str) -> Optional[dict]:
    tok = _key(data)
    if tok is None:
        return None
    with session_scope() as s:
        row = s.get(StudioToken, tok)
        if row is None:
            return None
        return {"kind": row.kind, "payload": json.loads(row.payload_json or "{}"),
                "slug": row.slug, "stop_id": row.stop_id, "used": row.used_at is not None}


def claim(data: str) -> Optional[dict]:
    """Mark the token used and return it; None if it is unknown or already used."""
    tok = _key(data)
    if tok is None:
        return None
    with session_scope() as s:
        res = s.exec(update(StudioToken)
                     .where(col(StudioToken.token) == tok, col(StudioToken.used_at).is_(None))
                     .values(used_at=datetime.utcnow()))
        s.commit()
        if res.rowcount != 1:
            return None
    return peek(data)


def release(data: str) -> None:
    """Undo a claim when the action failed before it changed anything, so Bo can tap again."""
    tok = _key(data)
    if tok is None:
        return
    with session_scope() as s:
        s.exec(update(StudioToken).where(col(StudioToken.token) == tok).values(used_at=None))
        s.commit()


def retire_stop(slug: str, stop_id: str) -> int:
    """Use up every button of an answered stop. Returns how many were still live."""
    with session_scope() as s:
        res = s.exec(update(StudioToken)
                     .where(col(StudioToken.slug) == slug, col(StudioToken.stop_id) == stop_id,
                            col(StudioToken.used_at).is_(None))
                     .values(used_at=datetime.utcnow()))
        s.commit()
        return res.rowcount
