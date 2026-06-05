"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { Play, MessageSquare } from "lucide-react";
import { api } from "@/lib/api";
import type { Agent } from "@/lib/types";
import { useAsync } from "@/lib/use-async";
import { StatusDot } from "@/components/ui/status-dot";
import { Sparkline } from "@/components/ui/sparkline";
import { TerminalCursor } from "@/components/ui/terminal-cursor";
import { SectionHeader } from "@/components/ui/section-header";
import { ErrorState } from "@/components/ui/error-state";
import { SkeletonCard } from "@/components/ui/loading-skeleton";
import { cn } from "@/lib/utils";

function relTime(iso?: string | null): string {
  if (!iso) return "never";
  const d = new Date(iso).getTime();
  if (Number.isNaN(d)) return "never";
  const s = Math.max(0, Math.round((Date.now() - d) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

function FleetCard({
  agent,
  spark,
  onChat,
}: {
  agent: Agent;
  spark: number[];
  onChat: () => void;
}) {
  const [running, setRunning] = useState(false);
  const isRunning = agent.status === "running" || running;

  async function run() {
    setRunning(true);
    try {
      await api.createJob(agent.id, `Run ${agent.name}`);
    } catch {
      setRunning(false);
    }
  }

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn(
        "surface-card group rounded-lg p-3 transition-shadow",
        isRunning && "live-glow border-brand/40",
      )}
    >
      <div className="flex items-center gap-2">
        <StatusDot status={isRunning ? "running" : agent.status ?? "idle"} />
        <span className="truncate font-mono text-sm font-semibold text-foreground">{agent.name}</span>
        <span className="ml-auto shrink-0">
          <Sparkline data={spark.length ? spark : [0, 0]} width={56} height={16} />
        </span>
      </div>

      <div className="mt-1.5 h-8">
        {isRunning && agent.current_task ? (
          <p className="line-clamp-2 font-mono text-[11px] text-brand/90">
            {agent.current_task}
            <TerminalCursor className="ml-0.5" />
          </p>
        ) : (
          <p className="line-clamp-2 text-[11px] text-muted-foreground">{agent.tagline}</p>
        )}
      </div>

      <div className="mt-1.5 flex items-center justify-between">
        <span className="font-mono text-[10px] uppercase tracking-wide text-muted-foreground/70">
          {agent.model?.replace("claude-", "").replace(/-\d+$/, "") ?? ""} · {relTime(agent.last_run_at)}
        </span>
        <div className="flex items-center gap-1 opacity-70 transition-opacity group-hover:opacity-100">
          <button onClick={run} aria-label={`run ${agent.name}`} className="rounded border border-border bg-surface-2 p-1 text-muted-foreground hover:text-brand">
            <Play className="h-3 w-3" />
          </button>
          <button onClick={onChat} aria-label={`chat ${agent.name}`} className="rounded border border-border bg-surface-2 p-1 text-muted-foreground hover:text-brand">
            <MessageSquare className="h-3 w-3" />
          </button>
        </div>
      </div>
    </motion.div>
  );
}

export function AgentFleet({
  byAgent,
  onSelectAgent,
}: {
  byAgent: Record<string, number[]>;
  onSelectAgent: (a: Agent) => void;
}) {
  const { data, loading, error, reload } = useAsync<Agent[]>(() => api.listAgents(), []);
  const runningCount = (data ?? []).filter((a) => a.status === "running").length;

  return (
    <div>
      <SectionHeader
        title="Agent fleet"
        description={data ? `${data.length} agents · ${runningCount} running` : "loading…"}
      />
      {loading ? (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {Array.from({ length: 6 }).map((_, i) => <SkeletonCard key={i} />)}
        </div>
      ) : error ? (
        <ErrorState message={error} onRetry={reload} />
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {(data ?? []).map((a) => (
            <FleetCard key={a.id} agent={a} spark={byAgent[a.id] ?? []} onChat={() => onSelectAgent(a)} />
          ))}
        </div>
      )}
    </div>
  );
}
