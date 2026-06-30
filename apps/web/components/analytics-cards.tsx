"use client";

import { motion } from "framer-motion";
import { Activity, Users } from "lucide-react";
import { useAsync } from "@/lib/use-async";
import { KpiCard } from "@/components/ui/kpi-card";
import { SectionHeader } from "@/components/ui/section-header";
import { DataTable, type Column } from "@/components/ui/data-table";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { SkeletonKpiStrip, SkeletonCard } from "@/components/ui/loading-skeleton";

interface Summary {
  total_runs: number;
  total_tokens: number;
  total_cost_usd: number;
  runs_by_agent: Record<string, { runs: number; tokens: number; cost_usd: number }>;
}
interface TimeseriesPoint {
  date: string;
  runs: number;
  tokens: number;
  cost_usd: number;
}

async function fetchJSON<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`Fetch failed: ${res.status}`);
  return res.json();
}

type AgentRow = { agent: string; runs: number };

export function AnalyticsCards() {
  const { data, loading, error, reload } = useAsync(
    () =>
      Promise.all([
        fetchJSON<Summary>("/api/analytics/summary"),
        fetchJSON<TimeseriesPoint[]>("/api/analytics/timeseries?days=14"),
      ]),
    [],
  );

  if (loading) {
    return (
      <div className="space-y-6">
        <SkeletonKpiStrip count={2} />
        <SkeletonCard />
      </div>
    );
  }
  if (error) return <ErrorState message={error} onRetry={reload} />;
  const [summary, timeseries] = data ?? [null, []];
  if (!summary || summary.total_runs === 0) {
    return <EmptyState title="No analytics yet" description="Message an agent to start collecting run data." icon={<Activity />} />;
  }

  const stats = [
    { label: "Total Runs", value: summary.total_runs.toLocaleString(), icon: <Activity className="h-4 w-4" /> },
    { label: "Active Agents", value: Object.keys(summary.runs_by_agent).length.toString(), icon: <Users className="h-4 w-4" /> },
  ];

  const maxRuns = Math.max(1, ...timeseries.map((t) => t.runs));

  const rows: AgentRow[] = Object.entries(summary.runs_by_agent)
    .map(([agent, s]) => ({ agent, runs: s.runs }))
    .sort((a, b) => b.runs - a.runs);

  const columns: Column<AgentRow>[] = [
    { key: "agent", header: "Agent", render: (r) => <span className="font-mono">{r.agent}</span> },
    { key: "runs", header: "Runs", numeric: true },
  ];

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {stats.map((s, i) => (
          <motion.div key={s.label} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}>
            <KpiCard label={s.label} value={s.value} icon={s.icon} />
          </motion.div>
        ))}
      </div>

      <div>
        <SectionHeader title="Runs over time" description="Last 14 days" />
        <div className="surface-card rounded-2xl p-5">
          <div className="flex h-48 items-end gap-2">
            {timeseries.map((point, i) => (
              <motion.div
                key={point.date}
                initial={{ height: 0 }}
                animate={{ height: `${(point.runs / maxRuns) * 100}%` }}
                transition={{ delay: i * 0.03, duration: 0.5 }}
                className="group relative min-h-[4px] flex-1 rounded-t-md bg-gradient-to-t from-brand to-purple-400"
              >
                <div className="absolute -top-8 left-1/2 -translate-x-1/2 whitespace-nowrap rounded border bg-popover px-2 py-1 text-xs opacity-0 transition-opacity group-hover:opacity-100">
                  {point.runs} runs
                </div>
              </motion.div>
            ))}
          </div>
          <div className="mt-2 flex justify-between text-xs text-muted-foreground">
            <span>{timeseries[0]?.date}</span>
            <span>{timeseries[timeseries.length - 1]?.date}</span>
          </div>
        </div>
      </div>

      <div>
        <SectionHeader title="Usage by agent" description="Runs per agent" />
        <DataTable columns={columns} rows={rows} getRowKey={(r) => r.agent} emptyTitle="No agent runs yet" />
      </div>
    </div>
  );
}
