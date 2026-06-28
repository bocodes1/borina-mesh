"use client";

import { useMemo, useState } from "react";
import { CalendarDays, ChevronLeft, ChevronRight, Plus, MapPin, Video } from "lucide-react";
import { api, type CalendarResponse, type CalendarEvent } from "@/lib/api";
import { eventStart } from "@/lib/calendar";
import { useAsync } from "@/lib/use-async";
import { Navbar } from "@/components/navbar";
import { SectionHeader } from "@/components/ui/section-header";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { SkeletonCard } from "@/components/ui/loading-skeleton";

type View = "month" | "week" | "day";

function startOfDay(d: Date) {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x;
}
function addDays(d: Date, n: number) {
  const x = new Date(d);
  x.setDate(x.getDate() + n);
  return x;
}
function rangeFor(anchor: Date, view: View): { from: Date; to: Date; days: Date[] } {
  if (view === "day") {
    const from = startOfDay(anchor);
    return { from, to: addDays(from, 1), days: [from] };
  }
  if (view === "week") {
    const from = addDays(startOfDay(anchor), -anchor.getDay()); // Sunday start
    const days = Array.from({ length: 7 }, (_, i) => addDays(from, i));
    return { from, to: addDays(from, 7), days };
  }
  // month
  const first = new Date(anchor.getFullYear(), anchor.getMonth(), 1);
  const gridStart = addDays(startOfDay(first), -first.getDay());
  const days = Array.from({ length: 42 }, (_, i) => addDays(gridStart, i));
  return { from: gridStart, to: addDays(gridStart, 42), days };
}

function timeLabel(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function EventPill({ ev }: { ev: CalendarEvent }) {
  const isTask = ev.kind === "task";
  return (
    <div className={`rounded-lg border px-2 py-1 text-xs ${isTask ? "border-warn/40 bg-warn/10 text-warn" : "border-brand/40 bg-brand/10 text-foreground"}`}>
      <div className="flex items-center gap-1">
        {!ev.all_day && ev.start ? <span className="tabular-nums text-muted-foreground">{timeLabel(ev.start)}</span> : null}
        <span className="truncate font-medium">{ev.title}</span>
      </div>
      {ev.location ? (
        <div className="mt-0.5 flex items-center gap-1 text-muted-foreground">
          <MapPin className="h-3 w-3" /> {ev.location}
        </div>
      ) : null}
      {ev.join_link ? (
        <a href={ev.join_link} className="mt-0.5 flex items-center gap-1 text-brand" target="_blank" rel="noreferrer">
          <Video className="h-3 w-3" /> join
        </a>
      ) : null}
    </div>
  );
}

export default function CalendarPage() {
  return (
    <main className="container mx-auto max-w-7xl px-4 py-6">
      <Navbar />
      <CalendarBody />
    </main>
  );
}

function CalendarBody() {
  const [view, setView] = useState<View>("week");
  const [anchor, setAnchor] = useState<Date>(() => new Date());
  const { from, to, days } = useMemo(() => rangeFor(anchor, view), [anchor, view]);
  const { data, loading, error, reload } = useAsync<CalendarResponse>(
    () => api.getCalendarEvents(from.toISOString(), to.toISOString()),
    [from.getTime(), to.getTime()],
  );
  const [showCreate, setShowCreate] = useState(false);

  const allEvents = useMemo(() => {
    if (!data) return [] as CalendarEvent[];
    return [...(data.events ?? []), ...(data.task_chips ?? [])];
  }, [data]);

  const eventsByDay = useMemo(() => {
    const map: Record<string, CalendarEvent[]> = {};
    for (const ev of allEvents) {
      const start = eventStart(ev);
      const key = start ? startOfDay(start).toDateString() : "";
      (map[key] ||= []).push(ev);
    }
    for (const k of Object.keys(map)) {
      map[k].sort((a, b) => (a.start ?? "").localeCompare(b.start ?? ""));
    }
    return map;
  }, [allEvents]);

  const step = view === "month" ? 30 : view === "week" ? 7 : 1;
  const label = anchor.toLocaleDateString([], { month: "long", year: "numeric", ...(view === "day" ? { day: "numeric" } : {}) });

  return (
    <div className="space-y-5">
      <SectionHeader
        title="Calendar"
        icon={<CalendarDays className="h-4 w-4" />}
        description={label}
        actions={
          <div className="flex items-center gap-2">
            <div className="flex rounded-lg border border-border bg-surface p-0.5">
              {(["month", "week", "day"] as View[]).map((v) => (
                <button
                  key={v}
                  onClick={() => setView(v)}
                  className={`rounded-md px-2.5 py-1 text-xs font-medium capitalize ${view === v ? "bg-brand text-white" : "text-muted-foreground hover:text-foreground"}`}
                >
                  {v}
                </button>
              ))}
            </div>
            <button onClick={() => setAnchor(addDays(anchor, -step))} aria-label="previous" className="rounded-md border border-border bg-surface p-1.5 text-muted-foreground hover:text-foreground">
              <ChevronLeft className="h-4 w-4" />
            </button>
            <button onClick={() => setAnchor(new Date())} className="rounded-md border border-border bg-surface px-2 py-1 text-xs text-muted-foreground hover:text-foreground">
              Today
            </button>
            <button onClick={() => setAnchor(addDays(anchor, step))} aria-label="next" className="rounded-md border border-border bg-surface p-1.5 text-muted-foreground hover:text-foreground">
              <ChevronRight className="h-4 w-4" />
            </button>
            <button onClick={() => setShowCreate(true)} className="flex items-center gap-1 rounded-lg bg-brand px-2.5 py-1.5 text-xs font-medium text-white">
              <Plus className="h-4 w-4" /> New
            </button>
          </div>
        }
      />

      {!data?.calendar?.connected ? (
        <div className="rounded-xl border border-warn/30 bg-warn/10 px-4 py-2 text-sm text-warn">
          Google Calendar not connected — showing task deadlines only. Complete OAuth to see events.
        </div>
      ) : null}

      {loading ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </div>
      ) : error ? (
        <ErrorState message={error} onRetry={reload} />
      ) : allEvents.length === 0 ? (
        <EmptyState title="Nothing scheduled" description="No events or task deadlines in this range." icon={<CalendarDays />} />
      ) : view === "month" ? (
        <div className="grid grid-cols-7 gap-1">
          {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((d) => (
            <div key={d} className="px-1 py-1 text-center text-xs font-medium text-muted-foreground">{d}</div>
          ))}
          {days.map((day) => {
            const evs = eventsByDay[day.toDateString()] ?? [];
            const inMonth = day.getMonth() === anchor.getMonth();
            return (
              <div key={day.toISOString()} className={`min-h-[84px] rounded-lg border border-border/40 p-1 ${inMonth ? "bg-surface" : "bg-surface/40 opacity-60"}`}>
                <div className="text-right text-xs tabular-nums text-muted-foreground">{day.getDate()}</div>
                <div className="mt-1 space-y-1">
                  {evs.slice(0, 3).map((ev) => <EventPill key={ev.id} ev={ev} />)}
                  {evs.length > 3 ? <div className="text-xs text-muted-foreground">+{evs.length - 3} more</div> : null}
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <div className={`grid gap-3 ${view === "week" ? "sm:grid-cols-2 lg:grid-cols-7" : "grid-cols-1"}`}>
          {days.map((day) => {
            const evs = eventsByDay[day.toDateString()] ?? [];
            return (
              <div key={day.toISOString()} className="surface-card rounded-2xl p-3">
                <div className="mb-2 text-sm font-medium">
                  {day.toLocaleDateString([], { weekday: "short", day: "numeric" })}
                </div>
                {evs.length === 0 ? (
                  <p className="text-xs text-muted-foreground">—</p>
                ) : (
                  <div className="space-y-1.5">{evs.map((ev) => <EventPill key={ev.id} ev={ev} />)}</div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {showCreate ? <CreateEventModal onClose={() => setShowCreate(false)} onCreated={reload} /> : null}
    </div>
  );
}

function CreateEventModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [summary, setSummary] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [location, setLocation] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!summary || !start || !end) {
      setMsg("Title, start and end are required.");
      return;
    }
    setBusy(true);
    setMsg(null);
    try {
      const res = await api.createCalendarEvent({ summary, start, end, location: location || undefined });
      if (res.connected) {
        onCreated();
        onClose();
      } else {
        setMsg(res.error ?? "Calendar not connected — event not created.");
      }
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" role="dialog" aria-label="Create event">
      <div className="surface-card w-full max-w-md rounded-2xl p-5">
        <h3 className="mb-3 text-lg font-semibold">New event</h3>
        <div className="space-y-2">
          <input value={summary} onChange={(e) => setSummary(e.target.value)} placeholder="Title" aria-label="event title" className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm" />
          <label className="block text-xs text-muted-foreground">Start
            <input type="datetime-local" value={start} onChange={(e) => setStart(e.target.value)} aria-label="event start" className="mt-1 w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm" />
          </label>
          <label className="block text-xs text-muted-foreground">End
            <input type="datetime-local" value={end} onChange={(e) => setEnd(e.target.value)} aria-label="event end" className="mt-1 w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm" />
          </label>
          <input value={location} onChange={(e) => setLocation(e.target.value)} placeholder="Location (optional)" aria-label="event location" className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm" />
        </div>
        {msg ? <p className="mt-2 text-sm text-warn">{msg}</p> : null}
        <div className="mt-4 flex justify-end gap-2">
          <button onClick={onClose} className="rounded-lg border border-border px-3 py-1.5 text-sm text-muted-foreground">Cancel</button>
          <button onClick={submit} disabled={busy} className="rounded-lg bg-brand px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50">Create</button>
        </div>
      </div>
    </div>
  );
}
