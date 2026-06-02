import * as React from "react";
import { AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";

interface ErrorStateProps extends Omit<React.HTMLAttributes<HTMLDivElement>, "title"> {
  title?: React.ReactNode;
  message?: React.ReactNode;
  /** When provided, renders a Retry button. */
  onRetry?: () => void;
  retryLabel?: string;
}

/**
 * Consistent error panel. Never leaves the user staring at a blank screen
 * when a fetch fails.
 */
export function ErrorState({
  title = "Something went wrong",
  message,
  onRetry,
  retryLabel = "Retry",
  className,
  ...props
}: ErrorStateProps) {
  return (
    <div
      className={cn(
        "surface-card rounded-2xl flex flex-col items-center justify-center text-center gap-2 px-6 py-10",
        className
      )}
      role="alert"
      {...props}
    >
      <AlertTriangle className="h-7 w-7 text-negative" />
      <p className="text-sm font-medium text-foreground">{title}</p>
      {message ? (
        <p className="max-w-md text-sm text-muted-foreground break-words">{message}</p>
      ) : null}
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="mt-2 rounded-lg border border-border bg-surface-2 px-3 py-1.5 text-sm font-medium text-foreground transition-colors hover:bg-surface"
        >
          {retryLabel}
        </button>
      ) : null}
    </div>
  );
}
