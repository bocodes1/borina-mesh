import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

vi.mock("@/lib/api", () => ({
  api: {
    listJobs: vi.fn(),
    listAgents: vi.fn(),
    getJobRuns: vi.fn(),
    listArtifacts: vi.fn(),
  },
}));

import { api } from "@/lib/api";
import { JobLog } from "@/components/job-log";
import { ArtifactList } from "@/components/artifact-list";

beforeEach(() => vi.clearAllMocks());

describe("JobLog — live run-log", () => {
  it("renders queued/running/done rows with live counts + telegram tag", async () => {
    vi.mocked(api.listJobs).mockResolvedValue([
      { id: 1, agent_id: "researcher", prompt: "verify stocks", status: "running", created_at: "", started_at: new Date().toISOString(), completed_at: null, kind: "telegram_dispatch" },
      { id: 2, agent_id: "trader", prompt: "bot health", status: "queued", created_at: "", started_at: null, completed_at: null, kind: "agent_run" },
      { id: 3, agent_id: "ceo", prompt: "brief", status: "completed", created_at: "", started_at: "2026-06-05T00:00:00Z", completed_at: "2026-06-05T00:00:05Z", kind: "agent_run" },
    ] as never);

    render(<JobLog />);
    await waitFor(() => expect(screen.getByText("verify stocks")).toBeInTheDocument());
    // live lifecycle states appear (header counter + row labels) — at least one each
    expect(screen.getAllByText(/running/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/queued/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("completed").length).toBeGreaterThanOrEqual(1);
    // all three rows rendered
    expect(screen.getByText("bot health")).toBeInTheDocument();
    expect(screen.getByText("brief")).toBeInTheDocument();
    // telegram-sourced job tagged
    expect(screen.getByText("tg")).toBeInTheDocument();
  });
});

describe("ArtifactList — telegram-sourced surfacing", () => {
  it("shows the source + original prompt for telegram artifacts", async () => {
    vi.mocked(api.listArtifacts).mockResolvedValue([
      { date: "2026-06-05", name: "researcher-1.pdf", size_bytes: 2048, modified: "", path: "2026-06-05/researcher-1.pdf", source: "telegram", agent: "researcher", prompt: "verify the daily report of my stocks" },
      { date: "2026-06-05", name: "finance-brief.md", size_bytes: 512, modified: "", path: "2026-06-05/finance-brief.md" },
    ] as never);

    render(<ArtifactList />);
    await waitFor(() => expect(screen.getByText("researcher-1.pdf")).toBeInTheDocument());
    expect(screen.getByText(/telegram/)).toBeInTheDocument();
    expect(screen.getByText(/verify the daily report of my stocks/)).toBeInTheDocument();
    // download link to the artifact endpoint
    expect(document.querySelector('a[href="/api/artifacts/2026-06-05/researcher-1.pdf"]')).toBeTruthy();
  });
});
