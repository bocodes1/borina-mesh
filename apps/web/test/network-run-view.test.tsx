import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, waitFor, act, fireEvent } from "@testing-library/react";

// Capture the activity callback so we can fire a mock event at a run node.
let activityCb: ((e: unknown) => void) | null = null;
vi.mock("@/lib/activity", () => ({
  subscribeToActivity: (cb: (e: unknown) => void) => {
    activityCb = cb;
    return () => { activityCb = null; };
  },
}));
vi.mock("@/lib/api", () => ({
  api: {
    listAgents: vi.fn(),
    getAgent: vi.fn(),
    createJob: vi.fn(),
    listRuns: vi.fn(),
    getRun: vi.fn(),
  },
}));

import { api } from "@/lib/api";
import { NetworkGraph } from "@/components/network-graph";

beforeEach(() => {
  activityCb = null;
  vi.mocked(api.listAgents).mockResolvedValue([
    { id: "researcher", name: "Researcher", emoji: "", tagline: "x", tools: [], model: "m", status: "idle" },
    { id: "trader", name: "Trader", emoji: "", tagline: "y", tools: [], model: "m", status: "idle" },
  ] as never);
  vi.mocked(api.listRuns).mockResolvedValue([
    { id: 7, mode: "mission", status: "running", node_counts: { done: 1, pending: 2 }, created_at: "", updated_at: "" },
  ] as never);
  vi.mocked(api.getRun).mockResolvedValue({
    run: { id: 7, mode: "mission", status: "running" },
    nodes: [
      { key: "research", agent: "researcher", kind: "read", status: "done", result: "r" },
      { key: "prices", agent: "trader", kind: "read", status: "active", result: null },
      { key: "synth", agent: "ceo", kind: "synthesize", status: "pending", result: null },
    ],
    edges: [
      { src: "research", dst: "synth" },
      { src: "prices", dst: "synth" },
    ],
  } as never);
});

describe("NetworkGraph — run view toggle", () => {
  it("defaults to the fleet view (hub<->agent)", async () => {
    const { container } = render(<NetworkGraph />);
    await waitFor(() => expect(container.querySelector('[data-node="researcher"]')).toBeTruthy());
    // No run nodes in the fleet view.
    expect(container.querySelector("[data-run-node]")).toBeNull();
  });

  it("toggling to the run view renders Task nodes + TaskEdges", async () => {
    const { container, getByRole } = render(<NetworkGraph />);
    await waitFor(() => expect(container.querySelector('[data-node="researcher"]')).toBeTruthy());

    fireEvent.click(getByRole("button", { name: /run/i }));

    await waitFor(() => expect(container.querySelector('[data-run-node="research"]')).toBeTruthy());
    expect(container.querySelector('[data-run-node="prices"]')).toBeTruthy();
    expect(container.querySelector('[data-run-node="synth"]')).toBeTruthy();
    // Real agent->agent edges, not a hub star.
    expect(container.querySelector('[data-run-edge="research->synth"]')).toBeTruthy();
    expect(container.querySelector('[data-run-edge="prices->synth"]')).toBeTruthy();
    // Status coloring is surfaced for the run-view.
    expect(container.querySelector('[data-run-node="research"][data-run-node-status="done"]')).toBeTruthy();

    // Toggle back to the fleet view.
    fireEvent.click(getByRole("button", { name: /fleet/i }));
    await waitFor(() => expect(container.querySelector('[data-node="researcher"]')).toBeTruthy());
    expect(container.querySelector("[data-run-node]")).toBeNull();
  });

  it("an edge pulses when its dst node's agent activates", async () => {
    const { container, getByRole } = render(<NetworkGraph />);
    await waitFor(() => expect(container.querySelector('[data-node="researcher"]')).toBeTruthy());
    fireEvent.click(getByRole("button", { name: /run/i }));
    await waitFor(() => expect(container.querySelector('[data-run-node="synth"]')).toBeTruthy());

    // synth's agent is "ceo"; firing a ceo activity should pulse edges into synth.
    act(() => {
      activityCb?.({ agent_id: "ceo", kind: "started", message: "synth", job_id: 1, timestamp: new Date().toISOString() });
    });
    await waitFor(() =>
      expect(container.querySelector('[data-run-edge="research->synth"][data-run-edge-active="true"]')).toBeTruthy(),
    );
  });
});
