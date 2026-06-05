"use client";

import { motion } from "framer-motion";
import { cn } from "@/lib/utils";

const GLYPH: Record<string, string> = {
  started: ">",
  running: ">",
  completed: "+",
  failed: "x",
  queued: ".",
  message: "»",
};
const COLOR: Record<string, string> = {
  started: "text-brand",
  running: "text-brand",
  completed: "text-positive",
  failed: "text-negative",
  queued: "text-muted-foreground",
  message: "text-brand-2",
};

export interface ActivityRow {
  ts: string;
  kind: string;
  agent?: string;
  text: string;
}

/** A single line in the live activity stream — animates in, mono, console glyph. */
export function ActivityFeedRow({ ts, kind, agent, text }: ActivityRow) {
  return (
    <motion.div
      layout
      initial={{ opacity: 0, x: -8 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.18 }}
      className="flex items-baseline gap-2 border-b border-foreground/5 py-1 font-mono text-xs"
    >
      <span className="shrink-0 tabular-nums text-muted-foreground/60">{ts}</span>
      <span className={cn("shrink-0 font-bold", COLOR[kind] ?? "text-muted-foreground")}>{GLYPH[kind] ?? "·"}</span>
      {agent ? <span className="shrink-0 text-foreground/80">{agent}</span> : null}
      <span className="truncate text-muted-foreground">{text}</span>
    </motion.div>
  );
}
