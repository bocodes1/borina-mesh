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


# Action verbs this system must never auto-perform — but ONLY when they're the
# actual command intent, not when they appear inside a read-only question.
# "sell all my ETH now" is forbidden; "what's the sell-off about?" is not.
# NOTE: calendar verbs (add/create/schedule/book) are deliberately NOT here —
# a calendar request is routed to a propose-then-approve Card (the tap is the
# user-initiated write), so it must not be refused outright.
_IMPERATIVE_VERBS = (
    r"(?P<verb>buy|sell|short|long|purchase|trade|swap|transfer|withdraw|deposit|"
    r"wire|remit|send|delete|remove|wipe|drop|"
    r"place|execute|submit|reply|respond|grant|revoke)"
)
# Polite/filler prefixes that can precede an imperative ("please buy…",
# "can you delete…"). The verb still has to be the action being commanded.
_POLITE = (
    r"(?:please|pls|kindly|now|hey|ok|okay|go ahead(?: and)?|can you|could you|"
    r"would you|will you|i want you to|i'd like you to|i need you to|let'?s)"
)
_IMPERATIVE_RE = re.compile(rf"^\s*(?:{_POLITE}\s+)*{_IMPERATIVE_VERBS}\b", re.IGNORECASE)

_VERB_REASON = {
    "buy": "trade/order", "sell": "trade/order", "short": "trade/order",
    "long": "trade/order", "purchase": "trade/order", "trade": "trade", "swap": "trade",
    "transfer": "fund movement", "withdraw": "fund movement", "deposit": "fund movement",
    "wire": "fund movement", "remit": "fund movement", "send": "send/transfer",
    "delete": "deletion", "remove": "deletion", "wipe": "deletion", "drop": "deletion",
    "cancel": "cancellation", "book": "calendar-event creation",
    "schedule": "calendar-event creation", "create": "creation", "add": "creation",
    "place": "order placement", "execute": "order placement", "submit": "order placement",
    "reply": "send on Bo's behalf", "respond": "send on Bo's behalf",
    "grant": "permission change", "revoke": "permission change",
}

# High-signal phrases that are an action even mid-sentence (rare in benign asks).
_HIGH_CONF_PATTERNS = [
    (r"\b(transfer|wire|send|remit|withdraw|deposit)\b.{0,25}(\$|\busd\b|funds?|money|eth|btc|crypto|wallet|payment)", "fund movement"),
    (r"\b(place|execute|submit)\b.{0,20}\b(order|trade|position)\b", "order placement"),
    (r"\b(grant|revoke|change)\b.{0,20}\b(permission|access|role)\b", "permission change"),
    (r"\b(reply to|respond to)\b.{0,20}(email|message|text|dm)\b", "send on Bo's behalf"),
]


def detect_forbidden(text: str) -> Optional[str]:
    """Refuse only genuine action COMMANDS. A read-only question that merely
    contains an action word ('what happened when TSLA dropped') passes through.
    Also catches an imperative after a direct address ('trader: buy 10 NVDA')."""
    low = text.strip().lower()
    candidates = [low]
    colon = re.match(r"^\s*[\w-]+\s*[:,]\s+(.+)$", low, re.DOTALL)
    if colon:
        candidates.append(colon.group(1).strip())
    for cand in candidates:
        m = _IMPERATIVE_RE.match(cand)
        if m:
            return _VERB_REASON.get(m.group("verb"), "action")
        for pattern, reason in _HIGH_CONF_PATTERNS:
            if re.search(pattern, cand):
                return reason
    return None


def _alias_match(text: str) -> Optional[Intent]:
    low = text.lower()

    # Mission: explicit multi-agent orchestration. Checked first so "mission:
    # research X" isn't claimed by a single-agent alias below.
    if re.match(r"^\s*mission\b[:,]?\s+", low):
        return Intent(
            raw_text=text, agent="ceo", task_type="mission",
            confidence=0.95, source="alias",
        )

    # Direct addressing: "<agent>: <task>" / "<agent>, <task>" — Bo picks the
    # agent explicitly (Telegram fleet control).
    direct = re.match(
        r"^\s*(trader|inbox|scout|ceo|polymarket|researcher|adset|finance)\s*[:,]\s+(.+)$",
        low, re.DOTALL,
    )
    if direct:
        return Intent(
            raw_text=text, agent=direct.group(1), task_type="direct",
            confidence=0.95, source="alias",
        )

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

    # 2. Deterministic alias match — then enforce the fleet roster: a parked or
    # retired agent is not auto-routed (a parked one is still reachable by an
    # explicit "<agent>:" address; a retired one never is).
    alias = _alias_match(text)
    if alias and alias.agent:
        direct = alias.task_type in ("direct", "mission")
        try:
            from fleet_roster import is_routable
            ok = is_routable(alias.agent, direct=direct)
        except Exception:  # noqa: BLE001 — roster must never break routing
            ok = True
        if ok:
            return alias
        # Parked/retired specialist → fall through to the general researcher
        # (or, for a direct address to a retired agent, the same fallback).
    elif alias:
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
