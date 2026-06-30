import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

vi.mock("@/lib/api", () => ({
  api: {
    getFinanceBrief: vi.fn(),
    regenerateFinanceBrief: vi.fn(),
  },
}));

import { api } from "@/lib/api";
import { FinanceBrief } from "@/components/finance-brief";

const TABLE_BRIEF = {
  trading_date: "2026-06-27",
  generated_at: "2026-06-27T05:00:00+00:00",
  duration_seconds: 0.3,
  markdown: [
    "# Morning Brief — 2026-06-27",
    "",
    "| Ticker | P/E | Peer median |",
    "| ------ | --- | ----------- |",
    "| AAPL   | 28  | 31          |",
    "",
    "**Crypto:** BTC $64,000 (+1.2% 24h)",
  ].join("\n"),
  error: null,
  data_source_status: { fmp: true },
  skipped_sections: [],
};

beforeEach(() => vi.clearAllMocks());

describe("FinanceBrief", () => {
  it("renders a markdown table as a real <table> (remark-gfm)", async () => {
    vi.mocked(api.getFinanceBrief).mockResolvedValue(TABLE_BRIEF as never);
    const { container } = render(<FinanceBrief />);

    await waitFor(() =>
      expect(screen.getByText("AAPL")).toBeInTheDocument()
    );

    const table = container.querySelector("table");
    expect(table).not.toBeNull();
    expect(container.querySelectorAll("th").length).toBe(3);
    expect(container.querySelectorAll("tbody tr").length).toBe(1);
    // The raw pipe wall must NOT survive as literal text.
    expect(screen.queryByText(/\| Ticker \| P\/E \|/)).toBeNull();
  });

  it("shows the amber banner when sources are skipped", async () => {
    vi.mocked(api.getFinanceBrief).mockResolvedValue({
      ...TABLE_BRIEF,
      skipped_sections: ["Macro snapshot — set FRED_API_KEY in .env to enable"],
    } as never);
    render(<FinanceBrief />);
    await waitFor(() =>
      expect(screen.getByText(/Some data sources are unconfigured/i)).toBeInTheDocument()
    );
  });
});
