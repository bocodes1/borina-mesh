"use client";

import { AnimatePresence } from "framer-motion";
import { ActivityFeedRow } from "@/components/ui/activity-feed-row";
import { TerminalCursor } from "@/components/ui/terminal-cursor";
import type { ActivityEvent } from "@/lib/use-activity";

const KIND_MAP: Record<string, string> = {
  started: "started",
  streaming: "running",
  completed: "completed",
  failed: "failed",
  scheduled: "queued",
};

function timeOf(iso: string) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "--:--:--" : d.toLocaleTimeString([], { hour12: false });
}

/** The heartbeat of the page: a real-time scrolling feed of agent events. */
export function LiveActivityStream({ events }: { events: ActivityEvent[] }) {
  return (
    <div className="surface-card flex h-full flex-col rounded-lg">
      <div className="flex items-center justify-between border-b border-foreground/8 px-3 py-2">
        <span className="flex items-center gap-1.5 font-mono text-xs font-semibold uppercase tracking-[0.12em] text-foreground/90">
          <span className="font-bold text-brand">&gt;</span> activity
          <TerminalCursor className="ml-0.5" />
        </span>
        <span className="font-mono text-[10px] tabular-nums text-muted-foreground">{events.length} events</span>
      </div>
      <div className="min-h-[280px] flex-1 overflow-y-auto px-3 py-1">
        {events.length === 0 ? (
          <p className="py-8 text-center font-mono text-xs text-muted-foreground">
            waiting for signal<TerminalCursor className="ml-0.5" />
          </p>
        ) : (
          <AnimatePresence initial={false}>
            {events.map((e, i) => (
              <ActivityFeedRow
                key={`${e.timestamp}-${e.agent_id}-${i}`}
                ts={timeOf(e.timestamp)}
                kind={KIND_MAP[e.kind] ?? e.kind}
                agent={e.agent_id}
                text={e.message}
              />
            ))}
          </AnimatePresence>
        )}
      </div>
    </div>
  );
}
