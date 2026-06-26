"""Contact enrichment (spec §1) — resolve the best hiring contact + a verified
email per company. Hunter by default (key from HUNTER_API_KEY), isolated behind
find_contact so Apollo could swap in later. Pure data: returns an
IntegrationResult, never sends anything. A company with no confident email yields
not_connected so the pipeline drops it (logged by the caller, never silent).
"""
from __future__ import annotations

from .base import IntegrationResult, env, http_get_json, not_connected, ok, safe

SOURCE = "contacts"
HUNTER_BASE = "https://api.hunter.io/v2/domain-search"
MIN_CONFIDENCE = 50  # below this we don't trust the email enough to cold-mail


@safe(SOURCE)
def find_contact(company: str, domain: str) -> IntegrationResult:
    """Best hiring contact + verified email for a domain. not_connected when no
    key, or when no email clears the confidence bar."""
    key = env("HUNTER_API_KEY")
    if not key:
        return not_connected(SOURCE, "HUNTER_API_KEY not set")
    raw = http_get_json(HUNTER_BASE, params={"domain": domain, "api_key": key})
    emails = ((raw or {}).get("data") or {}).get("emails") or []
    if not emails:
        return not_connected(SOURCE, f"no contacts found for {domain}")
    best = max(emails, key=lambda e: e.get("confidence", 0))
    if best.get("confidence", 0) < MIN_CONFIDENCE:
        return not_connected(SOURCE, f"no confident email for {domain}")
    name = " ".join(p for p in (best.get("first_name"), best.get("last_name")) if p) or None
    return ok(SOURCE, {
        "name": name,
        "email": best["value"],
        "confidence": best.get("confidence", 0),
        "domain": domain,
    })
