import { describe, it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { LiveValue } from "@/components/ui/live-value";
import { StatusDot } from "@/components/ui/status-dot";
import { Sparkline } from "@/components/ui/sparkline";
import { TerminalCursor } from "@/components/ui/terminal-cursor";
import { ActivityFeedRow } from "@/components/ui/activity-feed-row";

describe("LiveValue", () => {
  it("renders the initial value", () => {
    render(<LiveValue value={42} />);
    expect(screen.getByText("42")).toBeInTheDocument();
  });

  it("flashes and updates on change (no count-up)", () => {
    const { rerender } = render(<LiveValue value={42} countUp={false} />);
    rerender(<LiveValue value={99} countUp={false} />);
    const el = screen.getByText("99");
    expect(el).toBeInTheDocument();
    expect(el.className).toContain("value-flash");
  });

  it("counts up to the new number and settles on it", async () => {
    const { rerender } = render(<LiveValue value={0} durationMs={60} />);
    rerender(<LiveValue value={250} durationMs={60} />);
    await waitFor(() => expect(screen.getByText("250")).toBeInTheDocument(), { timeout: 1500 });
  });

  it("formats with a custom formatter", () => {
    render(<LiveValue value={1234.5} format={(n) => `$${n.toFixed(2)}`} />);
    expect(screen.getByText("$1234.50")).toBeInTheDocument();
  });
});

describe("StatusDot", () => {
  it("running uses the phosphor accent + run pulse", () => {
    render(<StatusDot status="running" />);
    const dot = screen.getByRole("status");
    expect(dot.className).toContain("text-brand");
    expect(dot.className).toContain("dot-run");
  });

  it("idle breathes (ambient motion at rest)", () => {
    render(<StatusDot status="idle" />);
    expect(screen.getByRole("status").className).toContain("dot-breathe");
  });

  it("error is not pulsing", () => {
    render(<StatusDot status="error" />);
    const dot = screen.getByRole("status");
    expect(dot.className).toContain("text-negative");
    expect(dot.className).not.toContain("dot-run");
  });
});

describe("Sparkline", () => {
  it("renders an svg line path for the data", () => {
    const { container } = render(<Sparkline data={[1, 3, 2, 5, 4]} />);
    const paths = container.querySelectorAll("path");
    expect(paths.length).toBeGreaterThanOrEqual(1);
    expect(container.querySelector("svg")).toBeTruthy();
  });

  it("does not throw on flat/short data", () => {
    const { container } = render(<Sparkline data={[7]} />);
    expect(container.querySelector("svg")).toBeTruthy();
  });
});

describe("TerminalCursor + ActivityFeedRow", () => {
  it("cursor blinks", () => {
    const { container } = render(<TerminalCursor />);
    expect(container.firstChild).toHaveClass("term-cursor");
  });

  it("activity row shows timestamp, agent, text", () => {
    render(<ActivityFeedRow ts="04:21:09" kind="completed" agent="researcher" text="brief written" />);
    expect(screen.getByText("04:21:09")).toBeInTheDocument();
    expect(screen.getByText("researcher")).toBeInTheDocument();
    expect(screen.getByText("brief written")).toBeInTheDocument();
  });
});
