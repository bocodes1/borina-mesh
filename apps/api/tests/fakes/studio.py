"""Hermetic Launch Studio fakes (M5): a scripted studio CLI, a Telegram
capture, a spawn recorder and table cleanup. Nothing here starts a process,
opens a socket or sends a message."""
from __future__ import annotations

import itertools
from types import SimpleNamespace
from typing import Optional

BO = 6452258223


class FakeStudio:
    """Stands in for dispatch.studio_client.runner: replies are scripted per
    studio subcommand (its first argument), and every call is recorded."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.replies: dict[str, tuple[Optional[int], str, str]] = {}

    def reply(self, sub: str, code: Optional[int], out: str, err: str = "") -> None:
        """`err` is stderr: the real CLI prints its own errors (`studio <name>: …`) there."""
        self.replies[sub] = (code, out, err)

    def __call__(self, argv, cwd, env, timeout):
        args = list(argv[4:])  # after: npx -y pnpm@12.8.1 studio
        self.calls.append(args)
        return self.replies.get(args[0] if args else "", (1, "FAIL nothing scripted\n", ""))

    def subcommands(self) -> list[str]:
        return [c[0] for c in self.calls if c]


def install(monkeypatch, tmp_path) -> SimpleNamespace:
    """Fake CLI in a temp STUDIO_DIR, Bo's chat allow-listed, every send captured,
    and detached runs recorded instead of started."""
    from dispatch import dispatcher, studio_client, studio_runner

    cli = FakeStudio()
    monkeypatch.setenv("STUDIO_DIR", str(tmp_path))
    monkeypatch.setenv("STUDIO_ENABLED", "1")
    monkeypatch.delenv("STUDIO_QUIET_HOURS", raising=False)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", str(BO))
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", str(BO))
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setattr(studio_client, "runner", cli)
    sent: list[dict] = []
    ids = itertools.count(1000)

    def _send(chat_id, text, reply_markup=None):
        mid = next(ids)
        sent.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup, "message_id": mid})
        return mid

    monkeypatch.setattr(dispatcher, "send_telegram_message", _send)
    monkeypatch.setattr(dispatcher, "answer_callback_query", lambda *a, **k: None)
    spawned: list[str] = []
    monkeypatch.setattr(studio_runner, "spawn_run", lambda slug: spawned.append(slug) or 4242)
    # A text that misses every command falls through to the converse lane, which
    # starts a real `claude -p` in a thread: record it instead.
    import routes.telegram as tg

    conversed: list[str] = []
    monkeypatch.setattr(tg, "_run_converse", lambda text, chat_id, heard="": conversed.append(text))
    return SimpleNamespace(cli=cli, sent=sent, spawned=spawned, conversed=conversed)


def clean_tables() -> None:
    from sqlalchemy import delete
    from sqlmodel import col

    from db import session_scope
    from models import PipelineRun, StudioBrief, StudioStop, StudioToken, TelegramThread

    with session_scope() as s:
        for model in (StudioToken, StudioBrief, StudioStop):
            s.exec(delete(model))
        s.exec(delete(TelegramThread).where(col(TelegramThread.agent_id) == "studio"))
        s.exec(delete(PipelineRun).where(col(PipelineRun.pipeline_id) == "studio-radar"))
        s.commit()


def tap(data: str, user: int = BO) -> dict:
    """One inline-button tap through the real, fail-closed entry point."""
    import routes.telegram as tg

    return tg.process_update({"update_id": 1, "callback_query": {"id": "cq-1", "from": {"id": user}, "data": data}})


def buttons(msg: dict) -> list[tuple[str, str]]:
    rows = (msg.get("reply_markup") or {}).get("inline_keyboard") or []
    return [(b["text"], b["callback_data"]) for row in rows for b in row]
