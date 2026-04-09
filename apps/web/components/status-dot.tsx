type Status = "idle" | "running" | "qa_flagged" | "error";

const COLORS: Record<Status, string> = {
  idle:       "bg-emerald-500",
  running:    "bg-sky-500 animate-pulse",
  qa_flagged: "bg-amber-500",
  error:      "bg-red-500",
};

export function StatusDot({ status }: { status: Status }) {
  return <span className={`inline-block w-2.5 h-2.5 rounded-full ${COLORS[status]}`} />;
}
