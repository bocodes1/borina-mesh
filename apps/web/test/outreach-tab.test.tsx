import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("@/lib/api", () => ({
  api: { getOutreachSummary: vi.fn() },
}));
vi.mock("next/navigation", () => ({ usePathname: () => "/outreach" }));

import { api } from "@/lib/api";
import OutreachPage from "@/app/outreach/page";

const pending = () => new Promise(() => {}); // never resolves → loading state
const hasSkeleton = (c: HTMLElement) => c.querySelector(".animate-pulse") !== null;

beforeEach(() => vi.clearAllMocks());

describe("/outreach tab — 3 states", () => {
  it("loading shows skeletons", () => {
    vi.mocked(api.getOutreachSummary).mockReturnValue(pending() as never);
    const { container } = render(<OutreachPage />);
    expect(hasSkeleton(container)).toBe(true);
  });

  it("data renders pipeline rows + counts, no raw undefined", async () => {
    vi.mocked(api.getOutreachSummary).mockResolvedValue({
      counts: { proposed: 1, sent: 2, replied: 1, skipped: 0, failed: 0 },
      rows: [
        { id: 1, company: "Acme AI", track: "swe", contact_email: "ada@acme.ai",
          status: "replied", subject: "Internship", is_followup: false,
          created_at: "2026-06-20", sent_at: "2026-06-20" },
      ],
      replies: [
        { outreach_item_id: 1, from_email: "ada@acme.ai", subject: "Re",
          flag: "interview", confirmed: false, received_at: "2026-06-21" },
      ],
      week: { sent: 2, replied: 1, awaiting_followup: 1 },
    } as never);
    const { container } = render(<OutreachPage />);
    expect(await screen.findByText("Acme AI")).toBeInTheDocument();
    expect(screen.getByText(/interview/i)).toBeInTheDocument();
    expect(container.textContent).not.toContain("undefined");
  });

  it("empty shows no-outreach state", async () => {
    vi.mocked(api.getOutreachSummary).mockResolvedValue({
      counts: { proposed: 0, sent: 0, replied: 0, skipped: 0, failed: 0 },
      rows: [], replies: [],
      week: { sent: 0, replied: 0, awaiting_followup: 0 },
    } as never);
    render(<OutreachPage />);
    expect(await screen.findByText(/No outreach yet/i)).toBeInTheDocument();
  });

  it("error shows retry", async () => {
    vi.mocked(api.getOutreachSummary).mockRejectedValue(new Error("boom"));
    render(<OutreachPage />);
    expect(await screen.findByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});
