"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { api } from "@/lib/api";
import type { Agent, Run, RunDetail } from "@/lib/types";
import { subscribeToActivity } from "@/lib/activity";
import { initNodes, stepSimulation, type SimNode, type SimEdge } from "@/lib/force-sim";

const W = 820;
const H = 540;
const HUB = "mesh";

interface Particle {
  id: number;
  edge: string; // agent id (edge mesh<->agent)
  t: number; // 0..1
}

type View = "fleet" | "run";

export function NetworkGraph() {
  const [view, setView] = useState<View>("fleet");
  const [agents, setAgents] = useState<Agent[]>([]);
  const [, setTick] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);

  const nodesRef = useRef<SimNode[]>([]);
  const edgesRef = useRef<SimEdge[]>([]);
  const activeRef = useRef<Record<string, number>>({}); // agentId -> expiry ms
  const particlesRef = useRef<Particle[]>([]);
  const pidRef = useRef(0);
  const msgTimesRef = useRef<number[]>([]);
  const dragRef = useRef<string | null>(null);
  const agentsRef = useRef<Agent[]>([]);
  const svgRef = useRef<SVGSVGElement>(null);

  // Build topology from agents, then poll so node status (running/idle/error)
  // stays live instead of a stale mount-time snapshot. The force-sim node
  // positions are only rebuilt when the agent set actually changes — a
  // status-only refresh preserves layout.
  useEffect(() => {
    let cancelled = false;
    const fetchAgents = () =>
      api.listAgents().then((list) => {
        if (cancelled) return;
        setAgents(list);
        agentsRef.current = list;
        const ids = [HUB, ...list.map((a) => a.id)];
        const existing = new Set(nodesRef.current.map((n) => n.id));
        const sameSet = existing.size === ids.length && ids.every((id) => existing.has(id));
        if (!sameSet) {
          nodesRef.current = initNodes(ids, W, H);
          edgesRef.current = list.map((a) => ({ source: HUB, target: a.id }));
        }
      }).catch(() => {});
    fetchAgents();
    const id = setInterval(fetchAgents, 8000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  // Live edge pulses on REAL activity.
  useEffect(() => {
    const unsub = subscribeToActivity((e) => {
      if (!e.agent_id) return;
      activeRef.current[e.agent_id] = Date.now() + 2200;
      particlesRef.current.push({ id: pidRef.current++, edge: e.agent_id, t: 0 });
      msgTimesRef.current.push(Date.now());
      setTick((n) => (n + 1) % 1000000);
    });
    return unsub;
  }, []);

  // Sim + particle loop.
  useEffect(() => {
    let raf = 0;
    let last = typeof performance !== "undefined" ? performance.now() : 0;
    const loop = (now: number) => {
      const dt = Math.min(2, (now - last) / 16.67) || 1;
      last = now;
      if (nodesRef.current.length) stepSimulation(nodesRef.current, edgesRef.current, { width: W, height: H });
      particlesRef.current = particlesRef.current
        .map((p) => ({ ...p, t: p.t + 0.025 * dt }))
        .filter((p) => p.t <= 1);
      setTick((n) => (n + 1) % 1000000);
      raf = requestAnimationFrame(loop);
    };
    if (typeof requestAnimationFrame !== "undefined") raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, []);

  const nodePos = useCallback((id: string) => nodesRef.current.find((n) => n.id === id), []);

  const toSvg = (clientX: number, clientY: number) => {
    const svg = svgRef.current;
    if (!svg) return { x: 0, y: 0 };
    const r = svg.getBoundingClientRect();
    const rw = r.width || W;
    const rh = r.height || H;
    return { x: ((clientX - r.left) / rw) * W, y: ((clientY - r.top) / rh) * H };
  };

  useEffect(() => {
    const move = (ev: PointerEvent) => {
      const id = dragRef.current;
      if (!id) return;
      const n = nodesRef.current.find((x) => x.id === id);
      if (!n) return;
      const p = toSvg(ev.clientX, ev.clientY);
      n.x = p.x; n.y = p.y; n.vx = 0; n.vy = 0;
    };
    const up = () => {
      const id = dragRef.current;
      if (id) { const n = nodesRef.current.find((x) => x.id === id); if (n) n.fixed = false; }
      dragRef.current = null;
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    return () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
  }, []);

  const now = Date.now();
  msgTimesRef.current = msgTimesRef.current.filter((t) => now - t < 60000);
  const msgPerMin = msgTimesRef.current.length;
  const activeLinks = Object.values(activeRef.current).filter((exp) => exp > now).length;
  const agentById = (id: string) => agentsRef.current.find((a) => a.id === id);

  return (
    <div className="surface-card relative overflow-hidden rounded-lg">
      <div className="absolute left-1/2 top-3 z-10 flex -translate-x-1/2 gap-0.5 rounded-md border border-foreground/10 bg-surface-2/90 p-0.5 font-mono text-[10px] backdrop-blur">
        <button
          type="button"
          onClick={() => setView("fleet")}
          aria-pressed={view === "fleet"}
          className={`rounded px-2 py-0.5 ${view === "fleet" ? "bg-brand/20 text-brand" : "text-muted-foreground hover:text-foreground"}`}
        >
          Fleet
        </button>
        <button
          type="button"
          onClick={() => setView("run")}
          aria-pressed={view === "run"}
          className={`rounded px-2 py-0.5 ${view === "run" ? "bg-brand/20 text-brand" : "text-muted-foreground hover:text-foreground"}`}
        >
          Run
        </button>
      </div>

      {view === "run" ? <RunView /> : (
      <>
      <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} className="grid-bg block h-[60vh] w-full" role="img" aria-label="agent network">
        {edgesRef.current.map((e) => {
          const a = nodePos(e.source);
          const b = nodePos(e.target);
          if (!a || !b) return null;
          const active = (activeRef.current[e.target] ?? 0) > now;
          return (
            <line
              key={`edge-${e.target}`}
              data-edge={e.target}
              data-edge-active={active ? "true" : "false"}
              x1={a.x} y1={a.y} x2={b.x} y2={b.y}
              stroke={active ? "hsl(var(--brand))" : "hsl(var(--foreground) / 0.1)"}
              strokeWidth={active ? 2 : 1}
              style={active ? { filter: "drop-shadow(0 0 4px hsl(var(--brand)))" } : undefined}
            />
          );
        })}
        {particlesRef.current.map((p) => {
          const a = nodePos(HUB);
          const b = nodePos(p.edge);
          if (!a || !b) return null;
          return <circle key={`p-${p.id}`} data-particle cx={a.x + (b.x - a.x) * p.t} cy={a.y + (b.y - a.y) * p.t} r={3} fill="hsl(var(--brand))" />;
        })}
        {nodesRef.current.map((n, i) => {
          const isHub = n.id === HUB;
          const agent = agentById(n.id);
          const running = agent?.status === "running" || (activeRef.current[n.id] ?? 0) > now;
          const r = isHub ? 16 : 11;
          // Alternate labels above/below so adjacent nodes can't collide.
          const labelY = isHub || i % 2 === 0 ? r + 13 : -(r + 6);
          const color = isHub
            ? "hsl(var(--brand-2))"
            : running
            ? "hsl(var(--brand))"
            : agent?.status === "error"
            ? "hsl(var(--negative))"
            : "hsl(var(--muted-foreground))";
          return (
            <g
              key={n.id}
              data-node={n.id}
              data-node-running={running ? "true" : "false"}
              transform={`translate(${n.x},${n.y})`}
              className="cursor-pointer"
              onPointerDown={(ev) => {
                dragRef.current = n.id;
                const nd = nodesRef.current.find((x) => x.id === n.id);
                if (nd) nd.fixed = true;
                (ev.target as Element).setPointerCapture?.(ev.pointerId);
              }}
              onClick={() => !isHub && setSelected(n.id)}
            >
              {running ? <circle r={r + 6} fill="none" stroke="hsl(var(--brand))" strokeWidth={1} opacity={0.4} className="dot-run" /> : null}
              <circle r={r} fill="hsl(var(--surface-2))" stroke={color} strokeWidth={2} />
              <circle r={3} fill={color} />
              <text y={labelY} textAnchor="middle" className="fill-foreground/80 font-mono" fontSize={10}>
                {isHub ? "MESH" : agent?.name ?? n.id}
              </text>
            </g>
          );
        })}
      </svg>

      <div className="pointer-events-none absolute left-3 top-3 flex flex-col gap-1 font-mono text-[10px] text-muted-foreground">
        <span className="flex items-center gap-1.5"><span className="inline-block h-2 w-2 rounded-full bg-brand" /> active link</span>
        <span className="flex items-center gap-1.5"><span className="inline-block h-2 w-2 rounded-full bg-muted-foreground" /> idle</span>
      </div>
      <div className="pointer-events-none absolute right-3 top-3 flex flex-col items-end gap-0.5 font-mono text-[10px] text-muted-foreground">
        <span><span className="tabular-nums text-brand">{activeLinks}</span> active links</span>
        <span><span className="tabular-nums text-foreground">{msgPerMin}</span> msg/min</span>
        <span className="tabular-nums">{agents.length} nodes</span>
      </div>

      {selected ? <NodePanel agentId={selected} onClose={() => setSelected(null)} /> : null}
      </>
      )}
    </div>
  );
}

// Status → node color for the run view (mirrors the fleet status palette).
function runNodeColor(status: string): string {
  switch (status) {
    case "done":
      return "hsl(var(--positive, var(--brand-2)))";
    case "active":
    case "ready":
      return "hsl(var(--brand))";
    case "failed":
      return "hsl(var(--negative))";
    case "awaiting_approval":
      return "hsl(var(--warning, var(--brand-2)))";
    case "blocked":
    case "skipped":
      return "hsl(var(--muted-foreground) / 0.5)";
    default: // pending
      return "hsl(var(--muted-foreground))";
  }
}

// The orchestration "run" view: render a single Run's DAG — Task nodes colored
// by status, TaskEdges as real agent→agent edges. An edge pulses when its dst
// node's agent shows activity (reuses subscribeToActivity, keyed on node key).
function RunView() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [runId, setRunId] = useState<number | null>(null);
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [, setTick] = useState(0);

  const nodesRef = useRef<SimNode[]>([]);
  const edgesRef = useRef<SimEdge[]>([]);
  const activeRef = useRef<Record<string, number>>({}); // node key -> expiry ms
  const detailRef = useRef<RunDetail | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  // Load the recent-runs list and default to the newest.
  useEffect(() => {
    let cancelled = false;
    api.listRuns().then((list) => {
      if (cancelled) return;
      setRuns(list);
      setRunId((cur) => cur ?? list[0]?.id ?? null);
    }).catch(() => {});
    return () => { cancelled = true; };
  }, []);

  // Load the selected run's DAG; rebuild the sim layout from its node keys.
  useEffect(() => {
    if (runId == null) return;
    let cancelled = false;
    api.getRun(runId).then((d) => {
      if (cancelled) return;
      setDetail(d);
      detailRef.current = d;
      nodesRef.current = initNodes(d.nodes.map((n) => n.key), W, H);
      edgesRef.current = d.edges.map((e) => ({ source: e.src, target: e.dst }));
      setTick((n) => (n + 1) % 1000000);
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [runId]);

  // Live pulse: an activity event for agent X lights every node whose agent==X.
  useEffect(() => {
    const unsub = subscribeToActivity((e) => {
      const d = detailRef.current;
      if (!d || !e.agent_id) return;
      let hit = false;
      for (const n of d.nodes) {
        if (n.agent === e.agent_id) { activeRef.current[n.key] = Date.now() + 2200; hit = true; }
      }
      if (hit) setTick((n) => (n + 1) % 1000000);
    });
    return unsub;
  }, []);

  // Sim loop.
  useEffect(() => {
    let raf = 0;
    const loop = () => {
      if (nodesRef.current.length) stepSimulation(nodesRef.current, edgesRef.current, { width: W, height: H });
      setTick((n) => (n + 1) % 1000000);
      raf = requestAnimationFrame(loop);
    };
    if (typeof requestAnimationFrame !== "undefined") raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, []);

  const nodePos = (id: string) => nodesRef.current.find((n) => n.id === id);
  const now = Date.now();
  const nodeByKey = (key: string) => detailRef.current?.nodes.find((n) => n.key === key);

  return (
    <>
      <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} className="grid-bg block h-[60vh] w-full" role="img" aria-label="run graph">
        {(detail?.edges ?? []).map((e) => {
          const a = nodePos(e.src);
          const b = nodePos(e.dst);
          if (!a || !b) return null;
          const active = (activeRef.current[e.dst] ?? 0) > now;
          return (
            <line
              key={`re-${e.src}-${e.dst}`}
              data-run-edge={`${e.src}->${e.dst}`}
              data-run-edge-active={active ? "true" : "false"}
              x1={a.x} y1={a.y} x2={b.x} y2={b.y}
              stroke={active ? "hsl(var(--brand))" : "hsl(var(--foreground) / 0.12)"}
              strokeWidth={active ? 2 : 1}
              style={active ? { filter: "drop-shadow(0 0 4px hsl(var(--brand)))" } : undefined}
            />
          );
        })}
        {(detail?.nodes ?? []).map((n, i) => {
          const p = nodePos(n.key);
          if (!p) return null;
          const active = n.status === "active" || (activeRef.current[n.key] ?? 0) > now;
          const color = runNodeColor(active ? "active" : n.status);
          const r = 12;
          const labelY = i % 2 === 0 ? r + 13 : -(r + 6);
          return (
            <g
              key={n.key}
              data-run-node={n.key}
              data-run-node-status={n.status}
              data-run-node-kind={n.kind}
              transform={`translate(${p.x},${p.y})`}
            >
              {active ? <circle r={r + 6} fill="none" stroke="hsl(var(--brand))" strokeWidth={1} opacity={0.4} className="dot-run" /> : null}
              <circle r={r} fill="hsl(var(--surface-2))" stroke={color} strokeWidth={2} />
              <circle r={3} fill={color} />
              <text y={labelY} textAnchor="middle" className="fill-foreground/80 font-mono" fontSize={10}>
                {n.key}
              </text>
              <text y={i % 2 === 0 ? r + 23 : -(r + 16)} textAnchor="middle" className="fill-muted-foreground font-mono" fontSize={8}>
                {n.agent}
              </text>
            </g>
          );
        })}
      </svg>

      <div className="pointer-events-auto absolute right-3 top-12 flex items-center gap-1 font-mono text-[10px] text-muted-foreground">
        {runs.length ? (
          <select
            aria-label="run"
            value={runId ?? ""}
            onChange={(ev) => setRunId(Number(ev.target.value))}
            className="rounded border border-foreground/10 bg-surface-2 px-1 py-0.5 text-foreground"
          >
            {runs.map((r) => (
              <option key={r.id} value={r.id}>
                #{r.id} {r.mode} · {r.status}
              </option>
            ))}
          </select>
        ) : (
          <span>no runs yet</span>
        )}
      </div>
    </>
  );
}

function NodePanel({ agentId, onClose }: { agentId: string; onClose: () => void }) {
  const [agent, setAgent] = useState<Agent | null>(null);
  useEffect(() => { api.getAgent(agentId).then(setAgent).catch(() => {}); }, [agentId]);
  return (
    <div className="absolute bottom-3 right-3 w-64 rounded-lg border border-foreground/10 bg-popover/95 p-3 backdrop-blur">
      <div className="mb-2 flex items-center justify-between">
        <span className="font-mono text-sm font-semibold">{agent?.name ?? agentId}</span>
        <button onClick={onClose} aria-label="close" className="text-muted-foreground hover:text-foreground">×</button>
      </div>
      <p className="mb-2 text-xs text-muted-foreground">{agent?.tagline ?? "…"}</p>
      <button
        onClick={() => api.createJob(agentId, `Run ${agent?.name ?? agentId}`).catch(() => {})}
        className="w-full rounded border border-border bg-surface-2 py-1 font-mono text-xs text-brand hover:bg-surface"
      >
        ▸ quick-run
      </button>
    </div>
  );
}
