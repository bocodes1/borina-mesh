"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { Check, X, CalendarPlus, ListChecks, Sparkles } from "lucide-react";
import { api, type DailyPlan, type PlanItem } from "@/lib/api";
import { useAsync } from "@/lib/use-async";
import { SectionHeader } from "@/components/ui/section-header";
import { SkeletonCard } from "@/components/ui/loading-skeleton";
import { ErrorState } from "@/components/ui/error-state";
import { cn } from "@/lib/utils";

function ItemRow({ item, onAct }: { item: PlanItem; onAct: (id: number, action: "approve" | "reject") => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const decided = item.status !== "proposed";

  async function act(action: "approve" | "reject") {
    setBusy(true);
    try {
      await onAct(item.id, action);
    } finally {
      setBusy(false);
    }
  }

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn(
        "flex items-center gap-3 rounded-lg border px-3 py-2",
        item.status === "approved" ? "border-positive/30 bg-positive/[0.06]"
          : item.status === "rejected" ? "border-border/40 bg-surface-2/40 opacity-60"
          : "border-border/50 bg-surface",
      )}
    >
      <span className="shrink-0 text-muted-foreground">
        {item.kind === "calendar" ? <CalendarPlus className="h-4 w-4 text-brand-2" /> : <ListChecks className="h-4 w-4 text-brand" />}
      </span>
      <div className="min-w-0 flex-1">
        <p className={cn("truncate text-sm", item.status === "rejected" ? "text-muted-foreground line-through" : "text-foreground")}>{item.title}</p>
        {item.rationale ? <p className="truncate font-mono text-[10px] text-muted-foreground/70">{item.rationale}</p> : null}
      </div>
      {decided ? (
        <span className={cn("shrink-0 font-mono text-[10px] uppercase", item.status === "approved" ? "text-positive" : "text-muted-foreground")}>{item.status}</span>
      ) : (
        <div className="flex shrink-0 items-center gap-1">
          <button onClick={() => act("approve")} disabled={busy} aria-label={`approve ${item.title}`} className="rounded border border-positive/40 bg-positive/10 p-1 text-positive hover:bg-positive/20 disabled:opacity-50">
            <Check className="h-3.5 w-3.5" />
          </button>
          <button onClick={() => act("reject")} disabled={busy} aria-label={`reject ${item.title}`} className="rounded border border-border bg-surface-2 p-1 text-muted-foreground hover:text-negative disabled:opacity-50">
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}
    </motion.div>
  );
}

export function TodaysPlan() {
  const { data, loading, error, reload } = useAsync<DailyPlan>(() => api.getDailyPlan(), []);
  const [generating, setGenerating] = useState(false);

  async function act(id: number, action: "approve" | "reject") {
    if (action === "approve") await api.approvePlanItem(id);
    else await api.rejectPlanItem(id);
    reload();
  }

  async function generate() {
    setGenerating(true);
    try {
      await api.generateDailyPlan();
      reload();
    } finally {
      setGenerating(false);
    }
  }

  if (loading) return <SkeletonCard />;
  if (error) return <ErrorState message={error} onRetry={reload} />;

  const tasks = data?.tasks ?? [];
  const calendar = data?.calendar ?? [];

  return (
    <div className="surface-card rounded-2xl p-4">
      <SectionHeader
        title="Today's plan"
        description="proposed by the planner — approve to commit"
        icon={<Sparkles className="h-4 w-4" />}
        actions={
          <button onClick={generate} disabled={generating} className="rounded-lg border border-border bg-surface-2 px-2.5 py-1 font-mono text-xs text-brand hover:bg-surface disabled:opacity-50">
            {generating ? "…" : data?.has_plan ? "regenerate" : "generate"}
          </button>
        }
      />
      {!data?.has_plan ? (
        <p className="text-sm text-muted-foreground">No plan yet — generate one (or it runs each morning). The planner proposes; nothing is written until you approve.</p>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <p className="mb-1.5 font-mono text-[10px] uppercase tracking-wide text-muted-foreground">tasks</p>
            <div className="space-y-1.5">
              {tasks.length ? tasks.map((i) => <ItemRow key={i.id} item={i} onAct={act} />) : <p className="text-xs text-muted-foreground">—</p>}
            </div>
          </div>
          <div>
            <p className="mb-1.5 font-mono text-[10px] uppercase tracking-wide text-muted-foreground">proposed calendar changes</p>
            <div className="space-y-1.5">
              {calendar.length ? calendar.map((i) => <ItemRow key={i.id} item={i} onAct={act} />) : <p className="text-xs text-muted-foreground">—</p>}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
