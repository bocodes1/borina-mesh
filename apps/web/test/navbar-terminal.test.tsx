import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// usePathname is the only next/navigation hook the navbar uses.
vi.mock("next/navigation", () => ({ usePathname: () => "/" }));

import { Navbar } from "@/components/navbar";

describe("navbar (Terminal removed)", () => {
  it("has no Terminal nav item and no /terminal link", () => {
    const { container } = render(<Navbar />);
    expect(screen.queryByText("Terminal")).not.toBeInTheDocument();
    expect(container.querySelector('a[href="/terminal"]')).toBeNull();
  });

  it("still shows the core tabs", () => {
    render(<Navbar />);
    for (const label of ["Mesh", "Network", "Analytics", "Jobs", "Files", "Finance"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });
});
