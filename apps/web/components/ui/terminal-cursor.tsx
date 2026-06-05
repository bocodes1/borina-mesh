import { cn } from "@/lib/utils";

/** Blinking block cursor for live/streaming elements. */
export function TerminalCursor({ className }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={cn("term-cursor inline-block h-[1em] w-[0.5ch] translate-y-[0.1em] bg-brand", className)}
    />
  );
}
