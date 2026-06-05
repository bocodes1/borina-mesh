import { cn } from "@/lib/utils";

interface SparklineProps {
  data: number[];
  width?: number;
  height?: number;
  className?: string;
  /** stroke color (defaults to phosphor brand). */
  stroke?: string;
  fill?: boolean;
}

/**
 * Tiny inline SVG sparkline so numbers have shape/movement. Flat data still
 * renders a baseline (never a blank box).
 */
export function Sparkline({
  data,
  width = 72,
  height = 22,
  className,
  stroke = "hsl(var(--brand))",
  fill = true,
}: SparklineProps) {
  const pts = data.length >= 2 ? data : [0, 0];
  const min = Math.min(...pts);
  const max = Math.max(...pts);
  const range = max - min || 1;
  const stepX = width / (pts.length - 1);
  const coords = pts.map((v, i) => {
    const x = i * stepX;
    const y = height - ((v - min) / range) * (height - 2) - 1;
    return [x, y] as const;
  });
  const line = coords.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const area = `${line} L${width},${height} L0,${height} Z`;

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={cn("overflow-visible", className)}
      aria-hidden
    >
      {fill ? <path d={area} fill="hsl(var(--brand) / 0.12)" stroke="none" /> : null}
      <path d={line} fill="none" stroke={stroke} strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}
