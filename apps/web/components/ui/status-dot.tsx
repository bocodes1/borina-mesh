"use client";

import { cn } from "@/lib/utils";

type Status = "running" | "idle" | "error" | "qa_flagged" | string;

const STYLES: Record<string, { color: string; anim: string; label: string }> = {
  running: { color: "text-brand", anim: "dot-run", label: "running" },
  idle: { color: "text-muted-foreground", anim: "dot-breathe", label: "idle" },
  error: { color: "text-negative", anim: "", label: "error" },
  qa_flagged: { color: "text-warn", anim: "", label: "flagged" },
};

/**
 * Mission-control status dot: filled accent dot, phosphor + pulse when running,
 * gently breathing when idle (the console never looks frozen). `currentColor`
 * drives the keyframe glow, so color comes from the text-* class.
 */
export function StatusDot({
  status,
  size = 9,
  className,
}: {
  status: Status;
  size?: number;
  className?: string;
}) {
  const s = STYLES[status] ?? STYLES.idle;
  return (
    <span
      role="status"
      aria-label={s.label}
      className={cn("inline-block rounded-full bg-current", s.color, s.anim, className)}
      style={{ width: size, height: size }}
    />
  );
}
