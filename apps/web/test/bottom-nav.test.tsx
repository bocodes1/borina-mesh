import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("next/navigation", () => ({ usePathname: () => "/" }));

import { BottomNav } from "@/components/bottom-nav";

describe("mobile bottom nav", () => {
  it("shows the primary tabs", () => {
    render(<BottomNav />);
    for (const label of ["Mesh", "Finance", "Daily", "Calendar"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(screen.getByText("More")).toBeInTheDocument();
    // Terminal must never appear.
    expect(screen.queryByText("Terminal")).not.toBeInTheDocument();
  });

  it('"More" opens a sheet with the secondary tabs', async () => {
    render(<BottomNav />);
    expect(screen.queryByText("Analytics")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "More tabs" }));
    expect(screen.getByText("Analytics")).toBeInTheDocument();
    expect(screen.getByText("Network")).toBeInTheDocument();
    expect(screen.getByText("Jobs")).toBeInTheDocument();
  });
});
