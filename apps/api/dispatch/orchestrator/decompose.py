"""The decompose contract — turn a CEO DAG JSON into validated Task/TaskEdge
rows, and degrade to today's behavior on any garbage.

The CEO emits a single JSON object `{"nodes":[{key,agent,kind,prompt,depends_on}]}`
(`dispatch/mission.py:26-29` discipline). `parse_dag` extracts it tolerantly (the
newline-collapse JSON repair, `dispatch/mission.py:59`). `validate_dag` rejects the
WHOLE DAG (→ None → caller degrades) on any of: a dependency cycle (Kahn's
algorithm), an out-of-roster agent, a >8-node cap, a dangling `depends_on`, or a
missing/duplicate synthesize/verify terminal pair. `build_dag` persists the rows;
`degrade` rebuilds today's mission/goal fallback when validation fails.

Roster (mirrors the safety invariant, `dispatch/mission.py:19`): a `read` node may
only target the read-only intel roster `MISSION_AGENTS`; a `write` node only the
write-capable allow-list `WRITE_AGENTS` (calendar-only v1 — the planner owns
calendar proposals); `synthesize`/`verify` are pinned to the CEO.
"""
from __future__ import annotations

import json
import re
from typing import Optional

from db import session_scope
from dispatch.mission import MISSION_AGENTS, _parse_subtasks
from models import RunTask, TaskEdge

# Write-capable roster — v1 is CALENDAR-ONLY; the planner owns calendar proposals.
# A write node always pauses for approval (it can never auto-run), so this is the
# set of agents a `write` node may be routed to, not a grant of autonomy.
WRITE_AGENTS = {"planner"}

MAX_NODES = 8
_VALID_KINDS = {"read", "write", "synthesize", "verify"}


def parse_dag(text: str) -> Optional[list[dict]]:
    """Tolerant extract of the `nodes` array from a CEO DAG JSON object.

    Returns the raw node dicts (unvalidated) or None. Mirrors the mission JSON
    repair: a bare `json.loads`, then a newline-collapse retry for pane-wrapped
    output (`dispatch/mission.py:55-61`)."""
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        raw = json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        try:
            raw = json.loads(re.sub(r"\n\s*", " ", m.group(0)))
        except Exception:  # noqa: BLE001
            return None
    if not isinstance(raw, dict):
        return None
    nodes = raw.get("nodes")
    if not isinstance(nodes, list):
        return None
    return nodes or None


def _roster_ok(kind: str, agent: str) -> bool:
    if kind == "read":
        return agent in MISSION_AGENTS
    if kind == "write":
        return agent in WRITE_AGENTS
    if kind in ("synthesize", "verify"):
        return agent == "ceo"
    return False


def _has_cycle(keys: set[str], deps: dict[str, list[str]]) -> bool:
    """Kahn's algorithm: if the ready frontier empties before all nodes are
    placed, there is a cycle."""
    indeg = {k: 0 for k in keys}
    children: dict[str, list[str]] = {k: [] for k in keys}
    for k, ds in deps.items():
        for d in ds:
            indeg[k] += 1
            children[d].append(k)
    frontier = [k for k, n in indeg.items() if n == 0]
    placed = 0
    while frontier:
        cur = frontier.pop()
        placed += 1
        for child in children[cur]:
            indeg[child] -= 1
            if indeg[child] == 0:
                frontier.append(child)
    return placed < len(keys)


def validate_dag(nodes: Optional[list[dict]]) -> Optional[list[dict]]:
    """Validate a parsed node list. Returns the nodes on success, None on ANY
    failure (the caller then degrades). Rules per spec §Decompose contract:
    cap, roster, no-cycle, dangling-ref, and the exactly-one synthesize/verify
    terminal pair with `verify` depending on `synthesize`."""
    if not nodes or not isinstance(nodes, list):
        return None
    if len(nodes) > MAX_NODES:
        return None

    keys: list[str] = []
    deps: dict[str, list[str]] = {}
    for n in nodes:
        if not isinstance(n, dict):
            return None
        key = n.get("key")
        agent = n.get("agent")
        kind = n.get("kind")
        if not key or not agent or kind not in _VALID_KINDS:
            return None
        if key in deps:  # duplicate key
            return None
        if not _roster_ok(kind, agent):
            return None
        keys.append(key)
        deps[key] = list(n.get("depends_on") or [])

    key_set = set(keys)
    for ds in deps.values():
        for d in ds:
            if d not in key_set:  # dangling reference
                return None

    if _has_cycle(key_set, deps):
        return None

    # Terminal gate: exactly one synthesize + one verify, verify depends on synth.
    synth = [n["key"] for n in nodes if n.get("kind") == "synthesize"]
    verify = [n for n in nodes if n.get("kind") == "verify"]
    if len(synth) != 1 or len(verify) != 1:
        return None
    if synth[0] not in deps[verify[0]["key"]]:
        return None

    return nodes


def build_dag(run_id: int, nodes: list[dict]) -> None:
    """Persist the validated DAG as RunTask + TaskEdge rows."""
    with session_scope() as s:
        for n in nodes:
            s.add(
                RunTask(
                    run_id=run_id,
                    key=n["key"],
                    agent=n["agent"],
                    kind=n.get("kind", "read"),
                    prompt=str(n.get("prompt") or ""),
                )
            )
        for n in nodes:
            for dep in (n.get("depends_on") or []):
                s.add(TaskEdge(run_id=run_id, src=dep, dst=n["key"]))
        s.commit()


def degrade(run_id: int, text: str, mode: str) -> None:
    """Build today's fallback DAG when the CEO output fails to parse/validate.

    mission → reuse `_parse_subtasks` for ≤4 read nodes + one synthesize, or a
    single researcher read node if even that fails. goal → a single read node
    over the raw goal text (`dispatch/goal.py` degrade-to-single)."""
    if mode == "goal":
        build_dag(
            run_id,
            [{"key": "m0", "agent": "researcher", "kind": "read", "prompt": text, "depends_on": []}],
        )
        return

    subs = _parse_subtasks(text)
    if subs:
        nodes = [
            {"key": f"r{i}", "agent": sub["agent"], "kind": "read", "prompt": sub["prompt"], "depends_on": []}
            for i, sub in enumerate(subs)
        ]
    else:
        nodes = [{"key": "r0", "agent": "researcher", "kind": "read", "prompt": text, "depends_on": []}]
    nodes.append(
        {"key": "synth", "agent": "ceo", "kind": "synthesize", "prompt": text,
         "depends_on": [n["key"] for n in nodes]}
    )
    build_dag(run_id, nodes)
