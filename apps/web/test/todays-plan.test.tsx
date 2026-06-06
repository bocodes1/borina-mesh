import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("@/lib/api", () => ({
  api: {
    getDailyPlan: vi.fn(),
    approvePlanItem: vi.fn(),
    rejectPlanItem: vi.fn(),
    generateDailyPlan: vi.fn(),
  },
}));

import { api } from "@/lib/api";
import { TodaysPlan } from "@/components/todays-plan";

const PLAN = {
  day: "2026-06-05",
  has_plan: true,
  raw: null,
  items: [],
  tasks: [{ id: 1, kind: "task", status: "proposed", title: "Prep for standup", rationale: "meeting today", payload: {}, committed_ref: null }],
  calendar: [{ id: 2, kind: "calendar", status: "proposed", title: "Focus block", rationale: "deep work", payload: {}, committed_ref: null }],
};

beforeEach(() => vi.clearAllMocks());

describe("TodaysPlan", () => {
  it("renders proposed tasks + calendar changes and approves an item", async () => {
    vi.mocked(api.getDailyPlan).mockResolvedValue(PLAN as never);
    vi.mocked(api.approvePlanItem).mockResolvedValue({ status: "approved" } as never);
    render(<TodaysPlan />);
    await waitFor(() => expect(screen.getByText("Prep for standup")).toBeInTheDocument());
    expect(screen.getByText("Focus block")).toBeInTheDocument();

    await userEvent.click(screen.getByLabelText("approve Focus block"));
    expect(api.approvePlanItem).toHaveBeenCalledWith(2);
  });

  it("rejects an item", async () => {
    vi.mocked(api.getDailyPlan).mockResolvedValue(PLAN as never);
    vi.mocked(api.rejectPlanItem).mockResolvedValue({ status: "rejected" } as never);
    render(<TodaysPlan />);
    await waitFor(() => expect(screen.getByText("Prep for standup")).toBeInTheDocument());
    await userEvent.click(screen.getByLabelText("reject Prep for standup"));
    expect(api.rejectPlanItem).toHaveBeenCalledWith(1);
  });

  it("offers to generate when there is no plan", async () => {
    vi.mocked(api.getDailyPlan).mockResolvedValue({ day: "x", has_plan: false, raw: null, items: [], tasks: [], calendar: [] } as never);
    render(<TodaysPlan />);
    await waitFor(() => expect(screen.getByText(/No plan yet/)).toBeInTheDocument());
    expect(screen.getByText("generate")).toBeInTheDocument();
  });
});
