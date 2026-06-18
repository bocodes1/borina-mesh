"""Structured Telegram cards — the inline-button channel (foundation §D).

A `Card` is a headline + lines + inline-button actions. One renderer turns it
into Telegram HTML text + a `reply_markup` inline keyboard; the callback
*receiver* already exists in routes/telegram.py — this supplies the missing
*sender*. The same channel is reused by L2 approval cards, L3 milestone
check-ins, and L4 fleet-health cards (each adds a callback_data prefix).

`callback_data` is capped by Telegram at 64 bytes; keep keys short (`cancel:1934`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from dispatch.telegram_format import escape_html, _render_inline

CALLBACK_MAX = 64


@dataclass
class Action:
    label: str
    data: str  # callback_data, must be <= 64 bytes

    def __post_init__(self):
        if len(self.data.encode("utf-8")) > CALLBACK_MAX:
            raise ValueError(f"callback_data too long (>{CALLBACK_MAX}B): {self.data!r}")


@dataclass
class Card:
    headline: str
    lines: list[str] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)
    buttons_per_row: int = 3


def render_card(card: Card) -> tuple[str, Optional[dict]]:
    """Card → (html_text, reply_markup|None). Buttons are chunked into rows."""
    parts = [f"<b>{escape_html(card.headline)}</b>"]
    for ln in card.lines:
        parts.append("• " + _render_inline(ln))
    text = "\n".join(parts)

    markup = None
    if card.actions:
        n = max(1, card.buttons_per_row)
        rows = [
            [{"text": a.label, "callback_data": a.data} for a in card.actions[i:i + n]]
            for i in range(0, len(card.actions), n)
        ]
        markup = {"inline_keyboard": rows}
    return text, markup


def send_card(chat_id: int, card: Card) -> Optional[int]:
    """Render + send a Card. Returns Telegram's message_id (or None offline)."""
    from dispatch import dispatcher

    text, markup = render_card(card)
    return dispatcher.send_telegram_message(chat_id, text, reply_markup=markup)
