"use client";

import { api, type PipelineRunStatus } from "@/lib/api";
import { useAsync } from "@/lib/use-async";

const LABELS: Record<string, string> = {
  "schedule-daily": "6am brief",
  planner: "6:30am plan",
  "operator-midday": "midday",
  "operator-eod": "eod",
  "operator-eod-learner": "profile learner",
};

function dotColor(p: PipelineRunStatus, maxAgeHours: number): string {
  if (!p.last_run_at) return "bg-negative";
  const ageHours = (Date.now() - new Date(p.last_run_at).getTime()) / 3_600_000;
  if (ageHours > maxAgeHours) return "bg-negative";
  if (p.last_run_ok === false) return "bg-amber-500";
  return "bg-positive";
}

/** Small last-run status strip for the four dedicated cron pipelines (6am
 * brief, 6:30am plan, midday/eod recap, nightly profile learner) — so
 * staleness like the operator_brain learner silently not writing for weeks
 * shows up here instead of going unnoticed. */
export function PipelineHealthStrip() {
  const { data } = useAsync(() => api.getPipelineHealth(), []);
  if (!data) return null;

  return (
    <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground" title="Pipeline health">
      {data.pipelines.map((p) => (
        <span key={p.pipeline_id} className="flex items-center gap-1.5" title={p.last_run_detail ?? undefined}>
          <span className={`h-1.5 w-1.5 rounded-full ${dotColor(p, data.max_age_hours)}`} />
          {LABELS[p.pipeline_id] ?? p.pipeline_id}
        </span>
      ))}
    </div>
  );
}
