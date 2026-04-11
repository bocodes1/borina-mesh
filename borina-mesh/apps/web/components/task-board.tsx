"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { AgentTask } from "@/lib/types";

const COLUMNS = [
  { key: "backlog", label: "Backlog" },
  { key: "assigned", label: "Assigned" },
  { key: "in_progress", label: "In Progress" },
  { key: "review", label: "Review" },
  { key: "done", label: "Done" },
] as const;

const PRIORITY_COLORS: Record<string, string> = {
  critical: "bg-red-500/20 text-red-400",
  high: "bg-orange-500/20 text-orange-400",
  medium: "bg-blue-500/20 text-blue-400",
  low: "bg-gray-500/20 text-gray-400",
};

export function TaskBoard() {
  const [tasks, setTasks] = useState<AgentTask[]>([]);

  const refresh = () => api.listTasks().then(setTasks).catch(() => {});
  useEffect(() => { refresh(); }, []);

  const moveTask = async (taskId: number, newStatus: string) => {
    await api.updateTask(taskId, { status: newStatus });
    refresh();
  };

  const nextStatus = (current: string): string | null => {
    const order = ["backlog", "assigned", "in_progress", "review", "done"];
    const idx = order.indexOf(current);
    return idx < order.length - 1 ? order[idx + 1] : null;
  };

  return (
    <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
      {COLUMNS.map((col) => {
        const colTasks = tasks.filter((t) => t.status === col.key);
        return (
          <div key={col.key} className="space-y-2">
            <h3 className="text-sm font-medium text-muted-foreground px-1">
              {col.label} <span className="text-xs">({colTasks.length})</span>
            </h3>
            {colTasks.map((task) => (
              <div key={task.id} className="rounded-lg border bg-card p-3 text-sm space-y-2">
                <div className="font-medium">{task.title}</div>
                <div className="flex items-center gap-2">
                  <span className={`text-xs px-1.5 py-0.5 rounded ${PRIORITY_COLORS[task.priority] ?? ""}`}>
                    {task.priority}
                  </span>
                  {task.assigned_agent && (
                    <span className="text-xs text-muted-foreground">{task.assigned_agent}</span>
                  )}
                </div>
                {nextStatus(task.status) && (
                  <button
                    className="w-full text-xs text-muted-foreground hover:text-foreground py-1"
                    onClick={() => moveTask(task.id, nextStatus(task.status)!)}
                  >
                    Move to {nextStatus(task.status)?.replace("_", " ")} →
                  </button>
                )}
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
}
