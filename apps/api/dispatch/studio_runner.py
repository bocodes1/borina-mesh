"""Detached `studio run <slug>` (M5).

Like the builder (dispatch/builder.py), each run lives in its own session
(start_new_session), so a mesh kickstart never kills a build halfway.
scripts/studio_run.py calls drive(), which tells Bo how the run ended: a
failure card with Retry, a paused card with Continue, one line when a project
is live or dropped, and nothing for a stop (the stop watcher cards it) or for a
project another run already holds."""
from __future__ import annotations

import os
import random
import subprocess
import time
from pathlib import Path
from typing import Callable, Optional

from dispatch import studio_client

REPO = Path(os.getenv("BORINA_REPO", str(Path.home() / "borina-mesh")))
BUSY_WAIT_S = 300
BUSY_MAX_TRIES = 144          # 12 h of five-minute waits
RUN_TIMEOUT_S = 24 * 3600     # backstop only: the studio limits each Claude session itself
DONE_STAGES = ("live", "dropped")


def spawn_run(slug: str) -> Optional[int]:
    """Start the detached runner for one project. Returns its pid, or None for a bad slug."""
    if not studio_client.SLUG_RE.match(slug or ""):
        return None
    py = REPO / "apps" / "api" / ".venv" / "bin" / "python"
    script = REPO / "scripts" / "studio_run.py"
    log = REPO / "logs" / f"studio-{slug}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("ab") as fh:
        proc = subprocess.Popen([str(py), str(script), "--slug", slug], stdout=fh, stderr=fh,
                                start_new_session=True, cwd=str(REPO))
    return proc.pid


def outcome(res: studio_client.StudioResult, slug: str) -> tuple[str, str]:
    """(kind, detail) for one `studio run`; kind is stop | stage | locked | busy | fail."""
    last = res.last
    if res.code == 3 and last.startswith(f"STOP {slug} "):
        return "stop", last[len(f"STOP {slug} "):]
    if res.code == 0 and last.startswith(f"STAGE {slug} "):
        return "stage", last[len(f"STAGE {slug} "):]
    if res.code == 1 and last.startswith(f"FAIL {slug} "):
        reason = last[len(f"FAIL {slug} "):]
        word = reason.split(" ", 1)[0]
        return (word, reason) if word in ("locked", "busy") else ("fail", reason)
    return "fail", res.error or "studio run ended without a result line"


def drive(slug: str, *, run: Optional[Callable[..., studio_client.StudioResult]] = None,
          sleep: Callable[[float], None] = time.sleep) -> str:
    run = run or studio_client.run
    kind, detail = "fail", ""
    for _ in range(BUSY_MAX_TRIES):
        res = run(["run", slug], timeout=RUN_TIMEOUT_S)
        for ln in res.lines:
            print(f"[studio-run] {ln}", flush=True)
        kind, detail = outcome(res, slug)
        if kind != "busy":
            break
        sleep(BUSY_WAIT_S + random.uniform(0, 60))
    else:
        kind, detail = "fail", "still waiting for a free run slot after 12 h"
    report(slug, kind, detail)
    return kind


def report(slug: str, kind: str, detail: str) -> None:
    from dispatch import dispatcher
    from dispatch import studio_tokens as tokens
    from dispatch.cards import send_card
    from dispatch.studio_cards import bo_chat, failure_card, paused_card
    from dispatch.telegram_format import format_telegram

    chat = bo_chat()
    if chat is None or kind in ("stop", "locked"):
        return
    if kind == "fail" and detail == "no progress at ready":
        # Headless studio-ops ends its run at ready: the token is Bo's to create, and his CA comes next.
        dispatcher.send_telegram_message(chat, format_telegram(
            f"{slug} is ready for launch. Create the token on pump.fun from your wallet, "
            f"then send /studio ca {slug} <CA>."))
        return
    if kind == "fail":
        tok = tokens.mint("retry", {"slug": slug}, slug=slug)
        send_card(chat, failure_card(slug, detail, tok, f"logs/studio-{slug}.log"))
    elif kind == "stage" and detail in DONE_STAGES:
        dispatcher.send_telegram_message(chat, format_telegram(f"{slug} is {detail}."))
    elif kind == "stage":
        tok = tokens.mint("retry", {"slug": slug}, slug=slug)
        send_card(chat, paused_card(slug, detail, tok))
