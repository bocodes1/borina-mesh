"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Activity, Zap, DollarSign, Users } from "lucide-react";
import { Card } from "@/components/ui/card";

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

export function AnalyticsCards() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [timeseries, setTimeseries] = useState<TimeseriesPoint[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      fetchJSON<Summary>("/api/analytics/summary"),
      fetchJSON<TimeseriesPoint[]>("/api/analytics/timeseries?days=14"),
    ])
      .then(([s, t]) => {
        setSummary(s);
        setTimeseries(t);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  if (loading) {
    return <div className="text-muted-foreground">Loading analytics...</div>;
  }

  if (!summary) {
    return <div className="text-muted-foreground">No data yet. Message an agent to see analytics.</div>;
  }

  const stats = [
    { label: "Total Runs", value: summary.total_runs.toLocaleString(), icon: Activity, color: "text-blue-400" },
    { label: "Tokens Used", value: summary.total_tokens.toLocaleString(), icon: Zap, color: "text-yellow-400" },
    { label: "Total Cost", value: `$${summary.total_cost_usd.toFixed(2)}`, icon: DollarSign, color: "text-green-400" },
    { label: "Active Agents", value: Object.keys(summary.runs_by_agent).length.toString(), icon: Users, color: "text-purple-400" },
  ];

  const maxRuns = Math.max(1, ...timeseries.map((t) => t.runs));

  return (
    <div className="space-y-6">
      {/* KPI grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {stats.map((stat, i) => (
          <motion.div
            key={stat.label}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.05 }}
          >
            <Card className="glass p-6">
              <div className="flex items-start justify-between">
                <div>
                  <div className="text-sm text-muted-foreground">{stat.label}</div>
                  <div className="text-3xl font-bold mt-1 tabular-nums">{stat.value}</div>
                </div>
                <stat.icon className={`h-5 w-5 ${stat.color}`} />
              </div>
            </Card>
          </motion.div>
        ))}
      </div>

      {/* Timeseries bar chart */}
      <Card className="glass p-6">
        <h3 className="text-lg font-semibold mb-4">Runs Over Time (14 days)</h3>
        <div className="flex items-end gap-2 h-48">
          {timeseries.map((point, i) => (
            <motion.div
              key={point.date}
              initial={{ height: 0 }}
              animate={{ height: `${(point.runs / maxRuns) * 100}%` }}
              transition={{ delay: i * 0.03, duration: 0.5 }}
              className="flex-1 bg-gradient-to-t from-primary to-purple-400 rounded-t-md min-h-[4px] relative group"
            >
              <div className="absolute -top-8 left-1/2 -translate-x-1/2 opacity-0 group-hover:opacity-100 transition-opacity bg-popover border rounded px-2 py-1 text-xs whitespace-nowrap">
                {point.runs} runs
              </div>
            </motion.div>
          ))}
        </div>
        <div className="flex justify-between mt-2 text-xs text-muted-foreground">
          <span>{timeseries[0]?.date}</span>
          <span>{timeseries[timeseries.length - 1]?.date}</span>
        </div>
      </Card>

      {/* Per-agent breakdown */}
      <Card className="glass p-6">
        <h3 className="text-lg font-semibold mb-4">Usage by Agent</h3>
        <div className="space-y-3">
          {Object.entries(summary.runs_by_agent)
            .sort((a, b) => b[1].runs - a[1].runs)
            .map(([agentId, stats]) => (
              <div key={agentId} className="flex items-center justify-between py-2 border-b border-border/50 last:border-0">
                <div className="font-mono text-sm">{agentId}</div>
                <div className="flex items-center gap-6 text-sm">
                  <span className="text-muted-foreground">{stats.runs} runs</span>
                  <span className="text-muted-foreground">{stats.tokens.toLocaleString()} tok</span>
                  <span className="text-green-400 font-mono tabular-nums">${stats.cost_usd.toFixed(3)}</span>
                </div>
              </div>
            ))}
        </div>
      </Card>
    </div>
  );
}
