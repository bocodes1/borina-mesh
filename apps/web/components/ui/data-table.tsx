import * as React from "react";
import { cn } from "@/lib/utils";
import { EmptyState } from "./empty-state";

export interface Column<T> {
  /** Stable key, also used as default header label source. */
  key: string;
  header: React.ReactNode;
  align?: "left" | "right" | "center";
  /** Mark numeric columns so they render tabular-nums and right-align by default. */
  numeric?: boolean;
  className?: string;
  render?: (row: T, index: number) => React.ReactNode;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  getRowKey: (row: T, index: number) => string;
  onRowClick?: (row: T, index: number) => void;
  /** Shown when rows is empty. */
  emptyTitle?: React.ReactNode;
  emptyDescription?: React.ReactNode;
  className?: string;
}

/**
 * Shared dense table used by Jobs, Watchlist, Analytics breakdowns, etc.
 * Numeric columns get tabular-nums + right alignment. Empty → EmptyState.
 */
export function DataTable<T>({
  columns,
  rows,
  getRowKey,
  onRowClick,
  emptyTitle = "Nothing here yet",
  emptyDescription,
  className,
}: DataTableProps<T>) {
  if (rows.length === 0) {
    return <EmptyState title={emptyTitle} description={emptyDescription} />;
  }

  const alignClass = (col: Column<T>) => {
    const a = col.align ?? (col.numeric ? "right" : "left");
    return a === "right" ? "text-right" : a === "center" ? "text-center" : "text-left";
  };

  return (
    <div className={cn("surface-card overflow-hidden rounded-2xl", className)}>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border/60 text-xs uppercase tracking-wide text-muted-foreground">
              {columns.map((col) => (
                <th
                  key={col.key}
                  className={cn("px-4 py-2.5 font-medium", alignClass(col), col.className)}
                >
                  {col.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr
                key={getRowKey(row, i)}
                onClick={onRowClick ? () => onRowClick(row, i) : undefined}
                className={cn(
                  "border-b border-border/30 last:border-0 transition-colors",
                  onRowClick && "cursor-pointer hover:bg-surface-2"
                )}
              >
                {columns.map((col) => (
                  <td
                    key={col.key}
                    className={cn(
                      "px-4 py-2.5 text-foreground/90",
                      alignClass(col),
                      col.numeric && "tabular-nums",
                      col.className
                    )}
                  >
                    {col.render
                      ? col.render(row, i)
                      : ((row as Record<string, React.ReactNode>)[col.key] ?? "—")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
