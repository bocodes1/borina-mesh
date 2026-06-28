import type { CalendarEvent } from "./api";

// All-day / date-only starts ("YYYY-MM-DD") must be read as LOCAL midnight.
// `new Date("2026-06-27")` parses as UTC midnight, which in a negative-offset
// zone (e.g. -04:00) renders on the previous day — the day-shift bug.
export function eventStart(ev: CalendarEvent): Date | null {
  if (!ev.start) return null;
  if (ev.all_day || /^\d{4}-\d{2}-\d{2}$/.test(ev.start)) {
    const m = ev.start.match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (m) return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  }
  return new Date(ev.start);
}
