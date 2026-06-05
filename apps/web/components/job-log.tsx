"use client";

import { useEffect, useMemo, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X } from "lucide-react";
import { api } from "@/lib/api";
import type { Job, AgentRun } from "@/lib/types";
import { SectionHeader } from "@/components/ui/section-header";
import { StatusDot } from "@/components/ui/status-dot";
import { LiveValue } from "@/components/ui/live-value";
import { EmptyState } from "@/components/ui/empty-state";
import { SkeletonRows } from "@/components/ui/loading-skeleton";
import { cn } from "@/lib/utils";

const DOT: Record<string, string> = {
  queued: "idle",
  pending: "idle",
  running: "running",
  completed: "idle",
  failed: "error",
  cancelled: "idle",
};
const COLOR: Record<string, string> = {
  queued: "text-warn",
  pending: "text-muted-foreground",
  running: "text-brand",
  completed: "text-positive",
  failed: "text-negative",
  cancelled: "text-muted-foreground",
};

function rel(iso?: string | null): string {
  if (!iso) return "";
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  return `${Math.floor(s / 3600)}h`;
}
function dur(j: Job): string {
  if (!j.started_at) return "—";
  const end = j.completed_at ? new Date(j.completed_at).getTime() : Date.now();
  const s = Math.max(0, Math.round((end - new Date(j.started_at).getTime()) / 1000));
  return `${s}s`;
}

export function JobLog() {
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [filter, setFilter] = useState<string>("all");
  const [selected, setSelected] = useState<Job | null>(null);

  useEffect(() => {
    let alive = true;
    const load = () => api.listJobs().then((j) => { if (alive) setJobs(j); }).catch(() => {});
    load();
    const id = setInterval(load, 4000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  const running = (jobs ?? []).filter((j) => j.status === "running").length;
  const queued = (jobs ?? []).filter((j) => j.status === "queued" || j.status === "pending").length;
  const filtered = useMemo(
    () => (jobs ?? []).filter((j) => filter === "all" || j.status === filter),
    [jobs, filter],
  );

  return (
    <div>
      <SectionHeader
        title="Run log"
        description="live — agent runs, queued → running → done"
        actions={
          <div className="flex items-center gap-3 font-mono text-xs">
            <span className="text-brand"><LiveValue value={running} countUp={false} /> running</span>
            <span className="text-warn"><LiveValue value={queued} countUp={false} /> queued</span>
            <select
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              aria-label="filter status"
              className="rounded border border-border bg-surface px-2 py-1 text-xs"
            >
              {["all", "running", "queued", "completed", "failed"].map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
        }
      />

      {jobs === null ? (
        <div className="surface-card rounded-lg p-4"><SkeletonRows rows={6} cols={1} /></div>
      ) : filtered.length === 0 ? (
        <EmptyState title="No runs yet" description="Dispatch an agent to see it here." />
      ) : (
        <div className="surface-card overflow-hidden rounded-lg">
          <AnimatePresence initial={false}>
            {filtered.map((j) => {
              const active = j.status === "running" || j.status === "queued";
              return (
                <motion.button
                  key={j.id}
                  layout
                  initial={{ opacity: 0, y: -6 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  onClick={() => setSelected(j)}
                  className={cn(
                    "flex w-full items-center gap-3 border-b border-foreground/5 px-3 py-2 text-left font-mono text-xs last:border-0 hover:bg-surface-2",
                    active && "bg-brand/[0.04]",
                  )}
                >
                  <StatusDot status={DOT[j.status] ?? "idle"} size={8} />
                  <span className="w-10 shrink-0 tabular-nums text-muted-foreground/60">#{j.id}</span>
                  <span className="w-28 shrink-0 truncate text-foreground/90">{j.agent_id}</span>
                  <span className="flex-1 truncate text-muted-foreground">{j.prompt}</span>
                  {j.kind === "telegram_dispatch" ? <span className="shrink-0 rounded bg-brand-2/15 px-1.5 text-[10px] text-brand-2">tg</span> : null}
                  <span className={cn("w-16 shrink-0 text-right uppercase", COLOR[j.status])}>{j.status}</span>
                  <span className="w-10 shrink-0 text-right tabular-nums text-muted-foreground/60">{j.status === "completed" || j.status === "failed" ? dur(j) : rel(j.created_at)}</span>
                </motion.button>
              );
            })}
          </AnimatePresence>
        </div>
      )}

      {selected ? <JobDrawer job={selected} onClose={() => setSelected(null)} /> : null}
    </div>
  );
}

function JobDrawer({ job, onClose }: { job: Job; onClose: () => void }) {
  const [runs, setRuns] = useState<AgentRun[] | null>(null);
  useEffect(() => { api.getJobRuns(job.id).then(setRuns).catch(() => setRuns([])); }, [job.id]);

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/50" onClick={onClose} role="presentation">
      <motion.div
        initial={{ x: 40, opacity: 0 }}
        animate={{ x: 0, opacity: 1 }}
        onClick={(e) => e.stopPropagation()}
        className="h-full w-full max-w-md overflow-y-auto border-l border-foreground/10 bg-surface p-4"
        role="dialog"
        aria-label={`job ${job.id}`}
      >
        <div className="mb-3 flex items-center justify-between">
          <span className="flex items-center gap-2 font-mono text-sm font-semibold">
            <StatusDot status={DOT[job.status] ?? "idle"} /> #{job.id} {job.agent_id}
          </span>
          <button onClick={onClose} aria-label="close" className="text-muted-foreground hover:text-foreground"><X className="h-4 w-4" /></button>
        </div>
        <dl className="mb-3 grid grid-cols-3 gap-2 font-mono text-xs">
          <div><dt className="text-muted-foreground/60">status</dt><dd className={COLOR[job.status]}>{job.status}</dd></div>
          <div><dt className="text-muted-foreground/60">duration</dt><dd className="tabular-nums">{dur(job)}</dd></div>
          <div><dt className="text-muted-foreground/60">kind</dt><dd className="truncate">{job.kind ?? "agent_run"}</dd></div>
        </dl>
        <p className="mb-1 font-mono text-[10px] uppercase tracking-wide text-muted-foreground/60">input</p>
        <pre className="mb-3 whitespace-pre-wrap rounded border border-foreground/8 bg-surface-2 p-2 text-xs">{job.prompt}</pre>
        {job.error ? (
          <>
            <p className="mb-1 font-mono text-[10px] uppercase tracking-wide text-negative">error</p>
            <pre className="mb-3 whitespace-pre-wrap rounded border border-negative/20 bg-negative/5 p-2 text-xs text-negative">{job.error}</pre>
          </>
        ) : null}
        <p className="mb-1 font-mono text-[10px] uppercase tracking-wide text-muted-foreground/60">output</p>
        {runs === null ? (
          <p className="text-xs text-muted-foreground">loading…</p>
        ) : runs.length === 0 ? (
          <p className="text-xs text-muted-foreground">No output recorded.</p>
        ) : (
          runs.map((r) => (
            <pre key={r.id} className="whitespace-pre-wrap rounded border border-foreground/8 bg-surface-2 p-2 text-xs">{r.output}</pre>
          ))
        )}
      </motion.div>
    </div>
  );
}
