"""Fleet cards (L4) — weekly health report + auto-park notify/undo."""
from __future__ import annotations


def health_card(findings: list[dict]):
    """The weekly fleet-health Card. Idle agents get a Park button; failing/orphan
    findings are listed. Retire is only ever offered as a human-confirmed proposal."""
    from dispatch.cards import Card, Action

    if not findings:
        return Card(headline="Fleet health", lines=["All green — nothing to flag."])

    lines, actions = [], []
    for f in findings:
        who = f.get("agent") or f"job{f.get('job_id')}"
        lines.append(f"[{f['severity']}] {f['kind']} · {who} · {f['detail']}")
        if f["kind"] == "idle" and f.get("agent"):
            actions.append(Action(label=f"Park {f['agent'][:18]}", data=f"park:{f['agent']}"))
        if f["kind"] == "failing" and f.get("agent"):
            actions.append(Action(label=f"Retire {f['agent'][:16]}", data=f"retire:{f['agent']}"))
    return Card(headline=f"Fleet health — {len(findings)} finding(s)", lines=lines, actions=actions[:6])


def park_notice_card(agent_id: str, reason: str):
    """Notify + undo Card sent when the sweep auto-parks an idle agent."""
    from dispatch.cards import Card, Action

    return Card(
        headline=f"Parked {agent_id}",
        lines=[reason, "It won't run on its own. Tap to bring it back."],
        actions=[Action(label="Reactivate", data=f"unpark:{agent_id}")],
    )
