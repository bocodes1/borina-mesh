"""Intent router (spec §8b.3).

Free text → {agent, task_type, params, confidence}. Two stages:
1. deterministic alias/keyword match (cheap, no LLM) — covers the common cases
   incl. the worked example,
2. LLM fallback (Haiku) returning strict JSON when no alias matches.

Safety: a message whose intent maps to a *forbidden action* (trade/transfer/
send/delete/calendar-create/permission-change) is flagged here and never
dispatched. The router only ever picks among registered research/intel agents.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Optional

# Registered short agent ids (mirror agents/runner_v2.AGENT_REGISTRY).
KNOWN_AGENTS = {"trader", "inbox", "scout", "ceo", "polymarket", "researcher", "adset", "finance"}


@dataclass
class Intent:
    raw_text: str
    agent: Optional[str] = None
    task_type: Optional[str] = None
    params: dict = field(default_factory=dict)
    confidence: float = 0.0
    source: str = "none"  # alias | llm | none
    forbidden: bool = False
    forbidden_reason: Optional[str] = None
    clarify: bool = False

    @property
    def dispatchable(self) -> bool:
        return bool(self.agent) and not self.forbidden and not self.clarify

    def to_dict(self) -> dict:
        return {
            "agent": self.agent,
            "task_type": self.task_type,
            "params": self.params,
            "confidence": self.confidence,
            "source": self.source,
            "forbidden": self.forbidden,
            "forbidden_reason": self.forbidden_reason,
            "clarify": self.clarify,
        }


def _threshold() -> float:
    try:
        return float(os.getenv("INTENT_CONFIDENCE_THRESHOLD", "0.6"))
    except ValueError:
        return 0.6


# Verbs/phrases that imply an *action* this system must never auto-perform.
_FORBIDDEN_PATTERNS = [
    (r"\b(buy|sell|short|long|purchase)\b", "trade/order"),
    (r"\b(place|execute|submit)\b.{0,20}\b(order|trade)\b", "order placement"),
    (r"\b(trade|swap)\b", "trade"),
    (r"\b(transfer|withdraw|deposit|wire|remit)\b", "fund movement"),
    (r"\bsend\b.{0,25}(money|funds|usd|eth|btc|crypto|\$|payment)", "send funds"),
    (r"\b(reply to|respond to|send)\b.{0,20}(email|message|text|dm|him|her|them)\b", "send on Bo's behalf"),
    (r"\b(delete|remove|wipe|drop)\b", "deletion"),
    (r"\b(create|add|schedule|book)\b.{0,20}\b(event|meeting|calendar|invite)\b", "calendar-event creation"),
    (r"\b(grant|change|revoke)\b.{0,20}\b(permission|access|role)\b", "permission change"),
]


def detect_forbidden(text: str) -> Optional[str]:
    low = text.lower()
    for pattern, reason in _FORBIDDEN_PATTERNS:
        if re.search(pattern, low):
            return reason
    return None


def _alias_match(text: str) -> Optional[Intent]:
    low = text.lower()

    # Worked example (spec §8b.3): stocks/investments/portfolio + report/news/verify
    # → researcher + finance_deep_dive.
    finance_subject = re.search(r"\b(stock|stocks|investment|investments|portfolio|holdings|equit)", low)
    finance_action = re.search(r"\b(news|report|verify|check|update|review|daily)\b", low)
    if finance_subject and finance_action:
        return Intent(
            raw_text=text,
            agent="researcher",
            task_type="finance_deep_dive",
            params={"use_watchlist": True, "cross_check_daily_brief": True, "want_news": True},
            confidence=0.92,
            source="alias",
        )

    table = [
        (r"\b(polymarket|prediction market|odds)\b", "polymarket", "market_scan"),
        (r"\b(scout|product|ecommerce|kalodata|winning product)\b", "scout", "product_scan"),
        (r"\b(adset|ad set|campaign|ad spend|roas)\b", "adset", "ad_review"),
        (r"\b(inbox|email|triage|messages?)\b", "inbox", "inbox_triage"),
        (r"\b(bot health|cex|trader|trading bot)\b", "trader", "bot_health"),
        (r"\b(research|deep dive|investigate|look into|find out)\b", "researcher", "research"),
        (r"\b(brief|summary|ceo|strategy)\b", "ceo", "brief"),
    ]
    for pattern, agent, task_type in table:
        if re.search(pattern, low):
            return Intent(raw_text=text, agent=agent, task_type=task_type, confidence=0.8, source="alias")
    return None


def _classify_llm(text: str) -> dict:
    """LLM fallback. Routes to Haiku with a tight classifier prompt returning
    JSON {agent, task_type, params, confidence}. Tests monkeypatch this.

    The real call is intentionally lazy/guarded so importing this module never
    requires the Anthropic SDK or a key.
    """
    try:
        from agents.runner_v2 import run_agent_task_sync  # type: ignore
    except Exception:
        return {"agent": None, "confidence": 0.0}
    # In the live deploy this would invoke Haiku; offline we decline rather than guess.
    return {"agent": None, "confidence": 0.0}


def resolve_intent(text: str) -> Intent:
    text = (text or "").strip()
    if not text:
        return Intent(raw_text=text, clarify=True)

    # 1. Forbidden-action gate FIRST — refuse before routing to any agent.
    reason = detect_forbidden(text)
    if reason:
        return Intent(raw_text=text, forbidden=True, forbidden_reason=reason, confidence=1.0, source="alias")

    # 2. Deterministic alias match.
    alias = _alias_match(text)
    if alias:
        return alias

    # 3. LLM fallback.
    raw = _classify_llm(text) or {}
    agent = raw.get("agent")
    conf = float(raw.get("confidence") or 0.0)
    if agent and agent in KNOWN_AGENTS and conf >= _threshold():
        return Intent(
            raw_text=text,
            agent=agent,
            task_type=raw.get("task_type"),
            params=raw.get("params") or {},
            confidence=conf,
            source="llm",
        )

    # 4. General-question fallback: a non-forbidden message no specialist
    # claimed goes to the read-only researcher with the raw text as its
    # prompt — natural speech (esp. voice notes) must always prompt the mesh,
    # never bounce with "rephrase". The forbidden gate above still refuses.
    return Intent(
        raw_text=text,
        agent="researcher",
        task_type="general_question",
        confidence=0.5,
        source="fallback",
    )
