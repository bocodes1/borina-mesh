import * as React from "react";
import { cn } from "@/lib/utils";

interface EmptyStateProps extends Omit<React.HTMLAttributes<HTMLDivElement>, "title"> {
  title: React.ReactNode;
  description?: React.ReactNode;
  icon?: React.ReactNode;
  /** Optional CTA (e.g. a "Connect Brokerage" button). */
  action?: React.ReactNode;
}

/**
 * Clean empty state. Every tab uses this instead of a blank screen or a raw
 * "undefined" — including the "Connect X" placeholders for unconnected
 * finance sources.
 */
export function EmptyState({
  title,
  description,
  icon,
  action,
  className,
  ...props
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "surface-card rounded-2xl flex flex-col items-center justify-center text-center gap-2 px-6 py-10",
        className
      )}
      role="status"
      {...props}
    >
      {icon ? (
        <div className="mb-1 text-muted-foreground/70 [&>svg]:h-8 [&>svg]:w-8">{icon}</div>
      ) : null}
      <p className="text-sm font-medium text-foreground">{title}</p>
      {description ? (
        <p className="max-w-sm text-sm text-muted-foreground">{description}</p>
      ) : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}
