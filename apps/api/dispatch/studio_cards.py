"""Launch Studio Telegram cards (M5).

Pure builders over the studio CLI's JSON (plain dicts) plus button tokens. All
card text is model-written or third-party, so every card is `plain`: escaped,
never rendered as markdown or links."""
from __future__ import annotations

import os
from typing import Optional

from dispatch.cards import Action, Card, render_card

TEXT_BUDGET = 4000  # under Telegram's 4096, with room for the headline's tags


def bo_chat() -> Optional[int]:
    """Bo's chat id, only when it is also on the inbound allow-list (contracts §9).
    Fail closed: unset, garbled or not allow-listed means None, and nothing is sent."""
    raw = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    try:
        chat = int(raw)
    except ValueError:
        return None
    from routes.telegram import _allowed_ids

    return chat if chat in _allowed_ids() else None


def fit(card: Card, budget: int = TEXT_BUDGET) -> Card:
    """Shorten the longest line until the rendered text fits. Cuts the plain text
    before escaping, so an HTML entity is never split."""
    for _ in range(60):
        text, _markup = render_card(card)
        if len(text) <= budget:
            return card
        if not card.lines:
            break
        i = max(range(len(card.lines)), key=lambda k: len(card.lines[k]))
        if len(card.lines[i]) < 20:
            break
        ln = card.lines[i]
        card.lines[i] = ln[: int(len(ln) * 0.7)].rstrip() + " …"
    card.lines = [ln[:200] for ln in card.lines[:3]]
    return card


def _usd(v: float) -> str:
    return f"${float(v):,.2f}"


def brief_card(b: dict, build: str, skip: str) -> Card:
    rank = f"#{b['rank']} " if b.get("rank") else ""
    return fit(Card(
        headline=f"{rank}{b['name']} (${b['ticker']}) · lane {b['lane']}",
        lines=[b["pitch"], f"Money loop: {b['moneyLoop']}", f"Attention: {b['attention']}",
               f"Larp source: {b['larpSource']}"],
        actions=[Action("Build", build), Action("Skip", skip)],
        plain=True,
    ))


def swings_card(pairs: list[tuple[dict, str]]) -> Card:
    return fit(Card(
        headline=f"Big swings, insane but long ({len(pairs)})",
        lines=[f"{b['name']} (${b['ticker']}) · lane {b['lane']}: {b['pitch']}" for b, _ in pairs],
        actions=[Action(f"Build ${b['ticker']}", tok) for b, tok in pairs],
        buttons_per_row=2,
        plain=True,
    ))


def stop_card(stop: dict, options: list[tuple[str, str]], missing_media: int = 0) -> Card:
    lines = [stop["body"]] if stop.get("body") else []
    if stop.get("costUsd") is not None:
        lines.append(f"Cost: {_usd(stop['costUsd'])}. Yes asks you to confirm once more.")
    if missing_media:
        lines.append(f"{missing_media} attachment(s) could not be sent; they are in the project folder.")
    lines.append("Reply to this card to send a note with your answer.")
    return fit(Card(
        headline=f"{stop['slug']} · {stop['title']}",
        lines=lines,
        actions=[Action(label, tok) for label, tok in options],
        buttons_per_row=2,
        plain=True,
    ))


def confirm_card(stop: dict, label: str, confirm: str, cancel: str) -> Card:
    cost = _usd(stop["costUsd"])
    return fit(Card(
        headline=f"Spend {cost}?",
        lines=[f"{stop['slug']} · {stop['title']}: {label}"],
        actions=[Action(f"Confirm {cost}", confirm), Action("Cancel", cancel)],
        plain=True,
    ))


def note_card(stop: dict, note: str, options: list[tuple[str, str]]) -> Card:
    return fit(Card(
        headline="Send your note with which answer?",
        lines=[f"{stop['slug']} · {stop['title']}", f"Note: {note}"],
        actions=[Action(label, tok) for label, tok in options],
        buttons_per_row=2,
        plain=True,
    ))


def failure_card(slug: str, reason: str, retry: str, log_hint: str) -> Card:
    return fit(Card(headline=f"{slug} stopped", lines=[reason, f"Log: {log_hint}"],
                    actions=[Action("Retry", retry)], plain=True))


def paused_card(slug: str, stage: str, cont: str) -> Card:
    return Card(headline=f"{slug} paused at {stage}",
                lines=["It used its session limit without reaching a stop. Continue when you're ready."],
                actions=[Action("Continue", cont)], plain=True)


def status_card(projects: list[dict], stops: list[dict], radar_line: str) -> Card:
    waiting: dict = {}
    for st in stops:
        waiting[st.get("slug")] = waiting.get(st.get("slug"), 0) + 1
    lines = []
    for p in projects:
        n = waiting.get(p.get("slug"), 0)
        tail = f" · {n} stop{'s' if n != 1 else ''} waiting" if n else ""
        lines.append(f"{p.get('name')} (${p.get('ticker')}) · {p.get('slug')} · {p.get('stage')}{tail}")
    lines = lines or ["No projects yet."]
    lines.append(radar_line)
    plural = "s" if len(projects) != 1 else ""
    return fit(Card(headline=f"Studio · {len(projects)} project{plural}", lines=lines, plain=True))
