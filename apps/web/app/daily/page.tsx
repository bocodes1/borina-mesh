"use client";

import { useState } from "react";
import { CloudSun, Plus, Sparkles, Target, ListChecks, Trash2 } from "lucide-react";
import { api, type DailySummary, type TaskItem } from "@/lib/api";
import { useAsync } from "@/lib/use-async";
import { Navbar } from "@/components/navbar";
import { SectionHeader } from "@/components/ui/section-header";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { SkeletonKpiStrip, SkeletonCard } from "@/components/ui/loading-skeleton";

const TAG_COLORS: Record<string, string> = {
  work: "bg-blue-500/15 text-blue-300",
  borina: "bg-brand/20 text-brand",
  trading: "bg-positive/15 text-positive",
  personal: "bg-surface-2 text-muted-foreground",
};

function TaskRow({ task, onToggle, onDelete }: { task: TaskItem; onToggle: () => void; onDelete: () => void }) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-border/40 bg-surface px-3 py-2">
      <input
        type="checkbox"
        checked={task.done}
        onChange={onToggle}
        aria-label={`toggle ${task.title}`}
        className="h-4 w-4 accent-[hsl(var(--brand))]"
      />
      <div className="min-w-0 flex-1">
        <p className={`truncate text-sm ${task.done ? "text-muted-foreground line-through" : "text-foreground"}`}>
          {task.title}
        </p>
        {task.due ? (
          <p className="text-xs text-muted-foreground tabular-nums">due {task.due.slice(0, 10)}</p>
        ) : null}
      </div>
      <span className={`rounded-md px-2 py-0.5 text-xs ${TAG_COLORS[task.tag] ?? TAG_COLORS.personal}`}>{task.tag}</span>
      <button onClick={onDelete} aria-label={`delete ${task.title}`} className="text-muted-foreground hover:text-negative">
        <Trash2 className="h-4 w-4" />
      </button>
    </div>
  );
}

export default function DailyPage() {
  return (
    <main className="container mx-auto max-w-7xl px-4 py-6">
      <Navbar />
      <DailyBody />
    </main>
  );
}

function DailyBody() {
  const { data, loading, error, reload } = useAsync<DailySummary>(() => api.getDailySummary(), []);
  const [newTitle, setNewTitle] = useState("");
  const [busy, setBusy] = useState(false);

  async function addTask() {
    if (!newTitle.trim()) return;
    setBusy(true);
    try {
      await api.createTask({ title: newTitle.trim(), tag: "personal" });
      setNewTitle("");
      reload();
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return (
      <div className="space-y-6">
        <SkeletonKpiStrip count={3} />
        <div className="grid gap-4 md:grid-cols-2">
          <SkeletonCard />
          <SkeletonCard />
        </div>
      </div>
    );
  }
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (!data) return <EmptyState title="No daily data" />;

  const weather = data.weather;
  const tldr = data.brief?.tldr;
  const focus = data.brief?.tasks_focus;
  const nudges = data.brief?.nudges;
  const tasks = data.open_tasks ?? [];

  return (
    <div className="space-y-6">
      {/* Today header */}
      <div className="surface-card rounded-2xl p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs uppercase tracking-wide text-muted-foreground">Today</p>
            <h1 className="text-2xl font-semibold tracking-tight tabular-nums">{data.date}</h1>
          </div>
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <CloudSun className="h-5 w-5" />
            {weather.connected && weather.data ? (
              <span>
                {weather.data.conditions} · {Math.round(weather.data.temp)}°
              </span>
            ) : (
              <span>Weather not connected</span>
            )}
          </div>
        </div>
        {tldr ? (
          <p className="mt-3 whitespace-pre-wrap text-sm text-foreground/80">{tldr}</p>
        ) : (
          <p className="mt-3 text-sm text-muted-foreground">
            No brief yet today — generate one from the data sources you’ve connected.
          </p>
        )}
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        {/* Tasks column */}
        <section>
          <SectionHeader title="Tasks" icon={<ListChecks className="h-4 w-4" />} description="Your day, tracked" />
          <div className="mb-3 flex gap-2">
            <input
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addTask()}
              placeholder="Quick add a task…"
              aria-label="new task title"
              className="flex-1 rounded-xl border border-border bg-surface px-3 py-2 text-sm outline-none focus:border-brand"
            />
            <button
              onClick={addTask}
              disabled={busy}
              className="flex items-center gap-1 rounded-xl bg-brand px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              <Plus className="h-4 w-4" /> Add
            </button>
          </div>
          {tasks.length === 0 ? (
            <EmptyState title="No open tasks" description="Add one above to get started." />
          ) : (
            <div className="space-y-2">
              {tasks.map((t) => (
                <TaskRow
                  key={t.id}
                  task={t}
                  onToggle={async () => {
                    await api.updateTask(t.id, { done: !t.done });
                    reload();
                  }}
                  onDelete={async () => {
                    await api.deleteTask(t.id);
                    reload();
                  }}
                />
              ))}
            </div>
          )}
        </section>

        {/* Focus + Agent suggestions */}
        <section className="space-y-6">
          <div>
            <SectionHeader title="Focus" icon={<Target className="h-4 w-4" />} description="What matters today" />
            <div className="surface-card rounded-2xl p-4">
              {focus ? (
                <p className="whitespace-pre-wrap text-sm text-foreground/85">{focus}</p>
              ) : (
                <p className="text-sm text-muted-foreground">Focus appears once the morning brief runs.</p>
              )}
            </div>
          </div>
          <div>
            <SectionHeader title="Agent suggestions" icon={<Sparkles className="h-4 w-4" />} description="Nudges from your morning brief" />
            <div className="surface-card rounded-2xl p-4">
              {nudges ? (
                <p className="whitespace-pre-wrap text-sm text-foreground/85">{nudges}</p>
              ) : (
                <p className="text-sm text-muted-foreground">No suggestions yet.</p>
              )}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
