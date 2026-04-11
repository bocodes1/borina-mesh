"use client";

const STATUS_STYLES: Record<string, { color: string; pulse: boolean }> = {
  running: { color: "bg-blue-500", pulse: true },
  idle: { color: "bg-gray-400", pulse: false },
  error: { color: "bg-red-500", pulse: false },
  qa_flagged: { color: "bg-yellow-500", pulse: false },
};

export function StatusDot({ status }: { status: string }) {
  const style = STATUS_STYLES[status] ?? STATUS_STYLES.idle;

  return (
    <div className="relative">
      <div className={`h-2.5 w-2.5 rounded-full ${style.color}`} />
      {style.pulse && (
        <div className={`absolute inset-0 h-2.5 w-2.5 rounded-full ${style.color} animate-ping opacity-75`} />
      )}
    </div>
  );
}
