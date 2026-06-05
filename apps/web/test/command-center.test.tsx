import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

vi.mock("@/lib/api", () => ({
  api: {
    listAgents: vi.fn(),
    listJobs: vi.fn(),
    createJob: vi.fn(),
  },
}));

import { api } from "@/lib/api";
import { LiveActivityStream } from "@/components/live-activity-stream";
import { AgentFleet } from "@/components/agent-fleet";
import { CommandStatusBar } from "@/components/command-status-bar";
import type { ActivityEvent } from "@/lib/use-activity";

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.listAgents).mockResolvedValue([]);
  vi.mocked(api.listJobs).mockResolvedValue([]);
});

describe("LiveActivityStream", () => {
  it("shows a waiting state with no events", () => {
    render(<LiveActivityStream events={[]} />);
    expect(screen.getByText(/waiting for signal/)).toBeInTheDocument();
  });

  it("renders event rows newest-first", () => {
    const events: ActivityEvent[] = [
      { agent_id: "researcher", kind: "completed", message: "brief written", job_id: 1, timestamp: "2026-06-05T04:21:09Z" },
      { agent_id: "trader", kind: "started", message: "bot health check", job_id: 2, timestamp: "2026-06-05T04:20:00Z" },
    ];
    render(<LiveActivityStream events={events} />);
    expect(screen.getByText("brief written")).toBeInTheDocument();
    expect(screen.getByText("bot health check")).toBeInTheDocument();
    expect(screen.getByText("2 events")).toBeInTheDocument();
  });
});

describe("AgentFleet — running is visibly distinct from idle", () => {
  it("glows only the running agent card", async () => {
    vi.mocked(api.listAgents).mockResolvedValue([
      { id: "a", name: "CEO", emoji: "", tagline: "x", tools: [], model: "claude-opus-4-8", status: "running", current_task: "synthesizing brief" },
      { id: "b", name: "Trader", emoji: "", tagline: "y", tools: [], model: "claude-sonnet-4-6", status: "idle" },
    ] as never);
    const { container } = render(<AgentFleet byAgent={{}} onSelectAgent={() => {}} />);
    await waitFor(() => expect(screen.getByText("CEO")).toBeInTheDocument());
    // exactly one card carries the live-glow (the running one)
    expect(container.querySelectorAll(".live-glow").length).toBe(1);
    // running agent shows its current task
    expect(screen.getByText("synthesizing brief")).toBeInTheDocument();
  });
});

describe("CommandStatusBar — alive at rest", () => {
  it("renders the online indicator and live cells", async () => {
    render(<CommandStatusBar />);
    expect(screen.getByText("online")).toBeInTheDocument();
    expect(screen.getByText("time")).toBeInTheDocument();
    expect(screen.getByText("uptime")).toBeInTheDocument();
    await waitFor(() => expect(api.listAgents).toHaveBeenCalled());
  });
});
