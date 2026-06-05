import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, waitFor, act } from "@testing-library/react";
import { initNodes, stepSimulation } from "@/lib/force-sim";

// Capture the activity callback so we can fire a mock message event.
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
});

describe("force-sim — the dead-graph guard", () => {
  it("node positions change across successive ticks", () => {
    const nodes = initNodes(["mesh", "a", "b", "c"], 820, 540);
    const edges = [
      { source: "mesh", target: "a" },
      { source: "mesh", target: "b" },
      { source: "mesh", target: "c" },
    ];
    const before = nodes.map((n) => ({ x: n.x, y: n.y }));
    for (let i = 0; i < 6; i++) stepSimulation(nodes, edges, { width: 820, height: 540 });
    const moved = nodes.some((n, i) => Math.abs(n.x - before[i].x) > 0.5 || Math.abs(n.y - before[i].y) > 0.5);
    expect(moved).toBe(true);
  });

  it("a settled node still differs from its initial ring position (not fixed coords)", () => {
    const nodes = initNodes(["mesh", "a", "b"], 820, 540);
    const edges = [{ source: "mesh", target: "a" }, { source: "mesh", target: "b" }];
    const a0 = { ...nodes[1] };
    for (let i = 0; i < 40; i++) stepSimulation(nodes, edges, { width: 820, height: 540 });
    expect(nodes[1].x !== a0.x || nodes[1].y !== a0.y).toBe(true);
  });
});

describe("NetworkGraph — edge animates on real message flow", () => {
  it("marks the agent's edge active when a message event fires", async () => {
    const { container } = render(<NetworkGraph />);
    await waitFor(() => expect(container.querySelector('[data-node="researcher"]')).toBeTruthy());

    // No active edge yet.
    expect(container.querySelector('[data-edge="researcher"][data-edge-active="true"]')).toBeNull();

    act(() => {
      activityCb?.({ agent_id: "researcher", kind: "started", message: "deep dive", job_id: 1, timestamp: new Date().toISOString() });
    });

    await waitFor(() =>
      expect(container.querySelector('[data-edge="researcher"][data-edge-active="true"]')).toBeTruthy(),
    );
  });
});
