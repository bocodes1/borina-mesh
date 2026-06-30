import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import { AnalyticsCards } from "@/components/analytics-cards";
import AnalyticsPage from "@/app/analytics/page";

const summary = {
  total_runs: 42,
  total_tokens: 0,
  total_cost_usd: 0,
  runs_by_agent: { researcher: { runs: 30, tokens: 0, cost_usd: 0 }, planner: { runs: 12, tokens: 0, cost_usd: 0 } },
};
const timeseries = [
  { date: "2026-06-13", runs: 5, tokens: 0, cost_usd: 0 },
  { date: "2026-06-14", runs: 7, tokens: 0, cost_usd: 0 },
];

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) =>
      Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(url.includes("timeseries") ? timeseries : summary),
      }),
    ),
  );
});
afterEach(() => vi.unstubAllGlobals());

describe("AnalyticsCards — no fake cost/token metrics", () => {
  it("renders real KPIs but never Tokens Used or Total Cost cards", async () => {
    render(<AnalyticsCards />);
    await waitFor(() => expect(screen.getByText("Total Runs")).toBeInTheDocument());
    expect(screen.getByText("Active Agents")).toBeInTheDocument();
    expect(screen.queryByText("Tokens Used")).not.toBeInTheDocument();
    expect(screen.queryByText("Total Cost")).not.toBeInTheDocument();
  });

  it("omits Tokens and Cost columns from the per-agent table", async () => {
    render(<AnalyticsCards />);
    await waitFor(() => expect(screen.getByText("researcher")).toBeInTheDocument());
    // Column headers
    expect(screen.getByText("Agent")).toBeInTheDocument();
    expect(screen.getByText("Runs")).toBeInTheDocument();
    expect(screen.queryByText("Tokens")).not.toBeInTheDocument();
    expect(screen.queryByText("Cost")).not.toBeInTheDocument();
  });
});

describe("AnalyticsPage subtitle", () => {
  it("describes run history and agent activity, not tokens/costs", () => {
    render(<AnalyticsPage />);
    expect(screen.getByText("Run history and agent activity.")).toBeInTheDocument();
    expect(screen.queryByText(/Token usage, costs/)).not.toBeInTheDocument();
  });
});
