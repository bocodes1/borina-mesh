"use client";

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

interface LiveValueProps {
  value: number | string;
  /** Formatter for numeric values (default: locale integer). */
  format?: (n: number) => string;
  /** Count up to new numeric values (default true). */
  countUp?: boolean;
  durationMs?: number;
  className?: string;
}

/**
 * A value that flashes the accent on change and counts up to new numbers — the
 * core "alive" primitive. Use it for every live count/price/PnL/token figure.
 */
export function LiveValue({
  value,
  format,
  countUp = true,
  durationMs = 450,
  className,
}: LiveValueProps) {
  const [display, setDisplay] = useState<number | string>(value);
  const [flash, setFlash] = useState(false);
  const prev = useRef<number | string>(value);
  const raf = useRef<number | null>(null);

  useEffect(() => {
    if (prev.current === value) return;
    setFlash(true);
    const clearFlash = setTimeout(() => setFlash(false), 550);

    const canAnimate =
      countUp &&
      typeof value === "number" &&
      typeof prev.current === "number" &&
      typeof requestAnimationFrame !== "undefined";

    if (canAnimate) {
      const from = prev.current as number;
      const to = value as number;
      const start = performance.now();
      const step = (now: number) => {
        const p = Math.min(1, (now - start) / durationMs);
        const eased = 1 - Math.pow(1 - p, 3);
        setDisplay(from + (to - from) * eased);
        if (p < 1) raf.current = requestAnimationFrame(step);
        else setDisplay(to);
      };
      raf.current = requestAnimationFrame(step);
    } else {
      setDisplay(value);
    }

    prev.current = value;
    return () => {
      clearTimeout(clearFlash);
      if (raf.current) cancelAnimationFrame(raf.current);
    };
  }, [value, countUp, durationMs]);

  const text =
    typeof display === "number"
      ? format
        ? format(display)
        : Math.round(display).toLocaleString()
      : String(display);

  return <span className={cn("tabular-nums", flash && "value-flash", className)}>{text}</span>;
}
