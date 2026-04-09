const COLORS: Record<string, string> = {
  "claude-opus-4-6": "bg-violet-100 text-violet-700",
  "claude-sonnet-4-6": "bg-sky-100 text-sky-700",
  "claude-haiku-4-5-20251001": "bg-emerald-100 text-emerald-700",
};

const LABELS: Record<string, string> = {
  "claude-opus-4-6": "Opus",
  "claude-sonnet-4-6": "Sonnet",
  "claude-haiku-4-5-20251001": "Haiku",
};

export function ModelBadge({ model }: { model: string }) {
  const cls = COLORS[model] ?? "bg-slate-100 text-slate-700";
  const label = LABELS[model] ?? model;
  return <span className={`text-xs font-medium px-1.5 py-0.5 rounded ${cls}`}>{label}</span>;
}
