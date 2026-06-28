"use client";

import { useEffect, useState } from "react";
import { LiveValue } from "@/components/ui/live-value";
import { api } from "@/lib/api";
import type { Agent, Job } from "@/lib/types";

interface Stats {
  active: number;
  queued: number;
  today: number;
}

function useInterval(fn: () => void, ms: number) {
  useEffect(() => {
    fn();
    const id = setInterval(fn, ms);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}

function fmtUptime(s: number) {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
}

function Cell({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex shrink-0 flex-col gap-0.5 border-l border-foreground/8 px-3 first:border-l-0 first:pl-0">
      <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground/70">{label}</span>
      <span className="font-mono text-sm font-semibold text-foreground">{children}</span>
    </div>
  );
}

export function CommandStatusBar({ agents: externalAgents }: { agents?: Agent[] } = {}) {
  const [clock, setClock] = useState("--:--:--");
  const [uptime, setUptime] = useState(0);
  const [stats, setStats] = useState<Stats>({ active: 0, queued: 0, today: 0 });
  const [localAgents, setLocalAgents] = useState<Agent[]>([]);
  const agents = externalAgents ?? localAgents;
  const [jobs, setJobs] = useState<Job[]>([]);

  // Ambient: clock + uptime tick every second so the bar is never frozen.
  useEffect(() => {
    const id = setInterval(() => {
      setClock(new Date().toLocaleTimeString([], { hour12: false }));
      setUptime((u) => u + 1);
    }, 1000);
    setClock(new Date().toLocaleTimeString([], { hour12: false }));
    return () => clearInterval(id);
  }, []);

  useInterval(() => { api.listJobs().then((j) => setJobs(j)).catch(() => {}); }, 12000);
  // Only self-poll /agents when no shared source was passed (e.g. standalone
  // usage). On the dashboard the parent's single poll feeds `externalAgents`.
  useInterval(() => { if (externalAgents) return; api.listAgents().then(setLocalAgents).catch(() => {}); }, 8000);
  useInterval(() => {
    fetch("/api/jobs/stats").then((r) => r.json()).then(setStats).catch(() => {});
  }, 5000);

  const total = agents.length;
  const running = agents.filter((a) => a.status === "running").length || stats.active;

  // Derived KPIs from real job data (no placeholders).
  const terminal = jobs.filter((j) => j.status === "completed" || j.status === "failed");
  const completed = terminal.filter((j) => j.status === "completed").length;
  const successRate = terminal.length ? Math.round((completed / terminal.length) * 100) : null;
  const durations = jobs
    .filter((j) => j.status === "completed" && j.started_at && j.completed_at)
    .map((j) => (new Date(j.completed_at as string).getTime() - new Date(j.started_at as string).getTime()) / 1000)
    .filter((d) => d >= 0);
  const avgLatency = durations.length ? Math.round(durations.reduce((a, b) => a + b, 0) / durations.length) : null;

  return (
    <div className="surface-card mb-6 flex items-center gap-1 overflow-x-auto rounded-lg px-3 py-2.5">
      <div className="flex shrink-0 items-center gap-2 pr-3">
        <span className="inline-block h-2 w-2 rounded-full bg-positive shadow-[0_0_8px_hsl(var(--positive))] dot-breathe" />
        <span className="font-mono text-[11px] uppercase tracking-[0.14em] text-positive">online</span>
      </div>
      <Cell label="time">{clock}</Cell>
      <Cell label="uptime">{fmtUptime(uptime)}</Cell>
      <Cell label="agents">
        <LiveValue value={running} countUp={false} />/<span className="text-muted-foreground">{total || "—"}</span>
      </Cell>
      <Cell label="running"><LiveValue value={stats.active} countUp={false} /></Cell>
      <Cell label="queued"><LiveValue value={stats.queued} countUp={false} /></Cell>
      <Cell label="runs·today"><LiveValue value={stats.today} /></Cell>
      <Cell label="success">{successRate == null ? "—" : <><LiveValue value={successRate} countUp={false} />%</>}</Cell>
      <Cell label="avg·lat">{avgLatency == null ? "—" : <><LiveValue value={avgLatency} countUp={false} />s</>}</Cell>
    </div>
  );
}
