import { describe, it, expect } from "vitest";
import { eventStart } from "@/lib/calendar";
import type { CalendarEvent } from "@/lib/api";

function ev(partial: Partial<CalendarEvent>): CalendarEvent {
  return { id: "x", title: "t", start: null, end: null, all_day: false, ...partial } as CalendarEvent;
}

describe("calendar eventStart — all-day day-shift fix", () => {
  it("parses a date-only all-day start as LOCAL midnight (no UTC day-shift)", () => {
    const d = eventStart(ev({ start: "2026-06-27", all_day: true }));
    expect(d).not.toBeNull();
    // Must land on the 27th in local time, not the 26th (the -04:00 bug).
    expect(d!.getFullYear()).toBe(2026);
    expect(d!.getMonth()).toBe(5); // June (0-indexed)
    expect(d!.getDate()).toBe(27);
    expect(d!.getHours()).toBe(0);
  });

  it("treats an all-day chip with a datetime start by its local date", () => {
    const d = eventStart(ev({ start: "2026-06-15T12:00:00", all_day: true }));
    expect(d!.getDate()).toBe(15);
  });

  it("parses a normal timed event with the native Date constructor", () => {
    const d = eventStart(ev({ start: "2026-06-27T09:30:00", all_day: false }));
    expect(d!.getDate()).toBe(27);
    expect(d!.getHours()).toBe(9);
  });

  it("returns null when there is no start", () => {
    expect(eventStart(ev({ start: null }))).toBeNull();
  });
});
