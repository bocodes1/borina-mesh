import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

// Mock the API client (every method the new tabs call).
vi.mock("@/lib/api", () => ({
  api: {
    getDailySummary: vi.fn(),
    createTask: vi.fn(),
    updateTask: vi.fn(),
    deleteTask: vi.fn(),
    getCalendarEvents: vi.fn(),
    createCalendarEvent: vi.fn(),
    getPortfolio: vi.fn(),
    // planner (TodaysPlan on the /daily page) — default to "no plan"
    getDailyPlan: vi.fn(() => Promise.resolve({ day: "", has_plan: false, raw: null, items: [], tasks: [], calendar: [] })),
    approvePlanItem: vi.fn(() => Promise.resolve({ status: "approved" })),
    rejectPlanItem: vi.fn(() => Promise.resolve({ status: "rejected" })),
    generateDailyPlan: vi.fn(() => Promise.resolve({})),
  },
}));
vi.mock("next/navigation", () => ({ usePathname: () => "/daily" }));

import { api } from "@/lib/api";
import DailyPage from "@/app/daily/page";
import CalendarPage from "@/app/calendar/page";
import { FinancePortfolio } from "@/components/finance-portfolio";

const pending = () => new Promise(() => {}); // never resolves → loading state
const hasSkeleton = (c: HTMLElement) => c.querySelector(".animate-pulse") !== null;

beforeEach(() => vi.clearAllMocks());

describe("/daily tab — 3 states", () => {
  it("loading shows skeletons", () => {
    vi.mocked(api.getDailySummary).mockReturnValue(pending() as never);
    const { container } = render(<DailyPage />);
    expect(hasSkeleton(container)).toBe(true);
  });

  it("data renders tasks + weather, no raw undefined", async () => {
    vi.mocked(api.getDailySummary).mockResolvedValue({
      date: "2026-06-02",
      has_brief: true,
      brief: { tldr: "Calm markets.", tasks_focus: "Ship it.", nudges: "Review watchlist." },
      weather: { source: "weather", connected: true, error: null, data: { temp: 60, conditions: "Clouds", description: "broken" } },
      open_tasks: [{ id: 1, title: "Ship rebuild", due: null, priority: "high", tag: "borina", done: false, sort_order: 0, created_at: "" }],
    } as never);
    const { container } = render(<DailyPage />);
    expect(await screen.findByText("Ship rebuild")).toBeInTheDocument();
    expect(screen.getByText(/Clouds/)).toBeInTheDocument();
    expect(container.textContent).not.toContain("undefined");
  });

  it("empty shows no-tasks state", async () => {
    vi.mocked(api.getDailySummary).mockResolvedValue({
      date: "2026-06-02", has_brief: false,
      brief: { tldr: null, tasks_focus: null, nudges: null },
      weather: { source: "weather", connected: false, error: "x", data: null },
      open_tasks: [],
    } as never);
    render(<DailyPage />);
    expect(await screen.findByText("No open tasks")).toBeInTheDocument();
  });

  it("error shows retry", async () => {
    vi.mocked(api.getDailySummary).mockRejectedValue(new Error("boom"));
    render(<DailyPage />);
    expect(await screen.findByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});

describe("/calendar tab — 3 states", () => {
  it("loading shows skeletons", () => {
    vi.mocked(api.getCalendarEvents).mockReturnValue(pending() as never);
    const { container } = render(<CalendarPage />);
    expect(hasSkeleton(container)).toBe(true);
  });

  it("data renders an event", async () => {
    // Event must fall in the calendar's default view (the current week).
    const start = new Date(); start.setHours(9, 0, 0, 0);
    const end = new Date(); end.setHours(9, 15, 0, 0);
    vi.mocked(api.getCalendarEvents).mockResolvedValue({
      calendar: { source: "google_calendar", connected: true, error: null, data: null },
      events: [{ id: "e1", title: "Standup", start: start.toISOString(), end: end.toISOString() }],
      task_chips: [],
    } as never);
    const { container } = render(<CalendarPage />);
    expect(await screen.findByText("Standup")).toBeInTheDocument();
    expect(container.textContent).not.toContain("undefined");
  });

  it("empty shows nothing-scheduled", async () => {
    vi.mocked(api.getCalendarEvents).mockResolvedValue({
      calendar: { source: "google_calendar", connected: false, error: "x", data: null },
      events: [], task_chips: [],
    } as never);
    render(<CalendarPage />);
    expect(await screen.findByText("Nothing scheduled")).toBeInTheDocument();
  });

  it("error shows retry", async () => {
    vi.mocked(api.getCalendarEvents).mockRejectedValue(new Error("nope"));
    render(<CalendarPage />);
    expect(await screen.findByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});

describe("finance portfolio strip — 3 states", () => {
  it("loading shows skeletons", () => {
    vi.mocked(api.getPortfolio).mockReturnValue(pending() as never);
    const { container } = render(<FinancePortfolio />);
    expect(hasSkeleton(container)).toBe(true);
  });

  it("connected renders positions", async () => {
    vi.mocked(api.getPortfolio).mockResolvedValue({
      net_worth: 12000,
      brokerage: { source: "brokerage", connected: true, error: null, data: { total_value: 9000, day_change: 10, day_change_pct: 1.2, positions: [{ symbol: "AAPL", qty: 5, value: 900, day_change_pct: 0.5 }], allocation: [] } },
      wallet: { source: "wallet", connected: true, error: null, data: { assets: [{ symbol: "ETH", balance: 1, value_usd: 3000, change_24h: 2 }], total_usd: 3000 } },
    } as never);
    const { container } = render(<FinancePortfolio />);
    expect(await screen.findByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("ETH")).toBeInTheDocument();
    expect(container.textContent).not.toContain("undefined");
  });

  it("not-connected shows Connect states", async () => {
    vi.mocked(api.getPortfolio).mockResolvedValue({
      net_worth: null,
      brokerage: { source: "brokerage", connected: false, error: "x", data: null },
      wallet: { source: "wallet", connected: false, error: "x", data: null },
    } as never);
    render(<FinancePortfolio />);
    expect(await screen.findByText("Brokerage not connected")).toBeInTheDocument();
    expect(screen.getByText("Wallet not connected")).toBeInTheDocument();
  });

  it("error shows retry", async () => {
    vi.mocked(api.getPortfolio).mockRejectedValue(new Error("fail"));
    render(<FinancePortfolio />);
    expect(await screen.findByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});
