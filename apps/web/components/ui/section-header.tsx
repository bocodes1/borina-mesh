import * as React from "react";
import { cn } from "@/lib/utils";

interface SectionHeaderProps extends Omit<React.HTMLAttributes<HTMLDivElement>, "title"> {
  title: React.ReactNode;
  description?: React.ReactNode;
  /** Optional content rendered on the right (filters, actions, live pill). */
  actions?: React.ReactNode;
  icon?: React.ReactNode;
}

/**
 * Consistent section title used across every tab. Tight tracking on the
 * header, muted description, right-aligned actions slot.
 */
export function SectionHeader({
  title,
  description,
  actions,
  icon,
  className,
  ...props
}: SectionHeaderProps) {
  return (
    <div
      className={cn("flex items-end justify-between gap-4 mb-4", className)}
      {...props}
    >
      <div className="min-w-0">
        <h2 className="flex items-center gap-2 text-lg font-semibold tracking-tight text-foreground">
          {icon ? <span className="text-muted-foreground">{icon}</span> : null}
          <span className="truncate">{title}</span>
        </h2>
        {description ? (
          <p className="mt-0.5 text-sm text-muted-foreground">{description}</p>
        ) : null}
      </div>
      {actions ? <div className="flex items-center gap-2 shrink-0">{actions}</div> : null}
    </div>
  );
}
