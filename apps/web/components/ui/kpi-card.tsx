import * as React from "react";
import { cn } from "@/lib/utils";

interface KpiCardProps extends React.HTMLAttributes<HTMLDivElement> {
  label: React.ReactNode;
  value: React.ReactNode;
  /** Secondary line under the value. */
  sublabel?: React.ReactNode;
  /** Signed delta string e.g. "+2.4%"; tone colors it. */
  delta?: React.ReactNode;
  deltaTone?: "positive" | "negative" | "neutral";
  icon?: React.ReactNode;
  /** Add the brief accent flash when the value updates (live data). */
  flash?: boolean;
}

const toneClass: Record<NonNullable<KpiCardProps["deltaTone"]>, string> = {
  positive: "text-positive",
  negative: "text-negative",
  neutral: "text-muted-foreground",
};

/**
 * KPI tile for the strip at the top of data-heavy tabs. Numbers use
 * tabular-nums so they don't jitter as live values update.
 */
export function KpiCard({
  label,
  value,
  sublabel,
  delta,
  deltaTone = "neutral",
  icon,
  flash,
  className,
  ...props
}: KpiCardProps) {
  return (
    <div
      className={cn("surface-card rounded-2xl p-4 flex flex-col gap-1", className)}
      {...props}
    >
      <div className="flex items-center justify-between">
        <span className="font-mono text-[11px] font-medium uppercase tracking-[0.1em] text-muted-foreground">
          {label}
        </span>
        {icon ? <span className="text-brand/70">{icon}</span> : null}
      </div>
      <div className="flex items-baseline gap-2">
        <span
          className={cn(
            "font-mono text-2xl font-semibold tabular-nums tracking-tight text-foreground",
            flash && "value-flash"
          )}
        >
          {value}
        </span>
        {delta != null ? (
          <span className={cn("text-sm font-medium tabular-nums", toneClass[deltaTone])}>
            {delta}
          </span>
        ) : null}
      </div>
      {sublabel ? (
        <span className="text-xs text-muted-foreground">{sublabel}</span>
      ) : null}
    </div>
  );
}
