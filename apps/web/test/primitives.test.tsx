import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { KpiCard } from "@/components/ui/kpi-card";
import { SectionHeader } from "@/components/ui/section-header";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { DataTable, type Column } from "@/components/ui/data-table";
import { Skeleton, SkeletonKpiStrip } from "@/components/ui/loading-skeleton";

describe("shared UI primitives", () => {
  it("KpiCard shows label, value, delta", () => {
    render(<KpiCard label="Runs" value="42" delta="+3" deltaTone="positive" />);
    expect(screen.getByText("Runs")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByText("+3")).toBeInTheDocument();
  });

  it("SectionHeader renders title + actions", () => {
    render(<SectionHeader title="Watchlist" actions={<button>Add</button>} />);
    expect(screen.getByText("Watchlist")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add" })).toBeInTheDocument();
  });

  it("EmptyState renders title + action", () => {
    render(<EmptyState title="No positions" action={<button>Connect</button>} />);
    expect(screen.getByText("No positions")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Connect" })).toBeInTheDocument();
  });

  it("ErrorState fires onRetry", async () => {
    const onRetry = vi.fn();
    render(<ErrorState message="boom" onRetry={onRetry} />);
    expect(screen.getByText("boom")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("DataTable renders rows and empty state", () => {
    type Row = { sym: string; last: number };
    const columns: Column<Row>[] = [
      { key: "sym", header: "Symbol" },
      { key: "last", header: "Last", numeric: true },
    ];
    const { rerender } = render(
      <DataTable columns={columns} rows={[{ sym: "AAPL", last: 1 }]} getRowKey={(r) => r.sym} />
    );
    expect(screen.getByText("AAPL")).toBeInTheDocument();

    rerender(
      <DataTable
        columns={columns}
        rows={[]}
        getRowKey={(r) => r.sym}
        emptyTitle="No tickers"
      />
    );
    expect(screen.getByText("No tickers")).toBeInTheDocument();
  });

  it("Skeletons render without throwing", () => {
    const { container } = render(
      <div>
        <Skeleton className="h-4 w-4" />
        <SkeletonKpiStrip count={2} />
      </div>
    );
    expect(container).toBeTruthy();
  });
});
