import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("@/lib/api", () => ({ api: { listFiles: vi.fn() } }));

import { api } from "@/lib/api";
import { FilesBrowser } from "@/components/files-browser";

const SAMPLE = {
  files: [
    { name: "daily-brief.md", path: "2026-06-05/daily-brief.md", date: "2026-06-05", modified: "", size_bytes: 512, type: "md", source: "schedule_daily", agent: "schedule_daily", prompt: null, job_id: null },
    { name: "researcher-7.pdf", path: "2026-06-05/researcher-7.pdf", date: "2026-06-05", modified: "", size_bytes: 2048, type: "pdf", source: "telegram", agent: "researcher", prompt: "verify stocks", job_id: 7 },
    { name: "notes.txt", path: "2026-06-05/notes.txt", date: "2026-06-05", modified: "", size_bytes: 20, type: "txt", source: "uploaded", agent: null, prompt: null, job_id: null },
  ],
  sources: ["schedule_daily", "telegram", "uploaded"],
  types: ["md", "pdf", "txt"],
  count: 3,
};

beforeEach(() => vi.clearAllMocks());

describe("FilesBrowser", () => {
  it("lists real files grouped by source, with search + filters", async () => {
    vi.mocked(api.listFiles).mockResolvedValue(SAMPLE as never);
    render(<FilesBrowser />);
    await waitFor(() => expect(screen.getByText("daily-brief.md")).toBeInTheDocument());
    expect(screen.getByText("researcher-7.pdf")).toBeInTheDocument();
    expect(screen.getByText("notes.txt")).toBeInTheDocument();
    // telegram-sourced file surfaces its original prompt
    expect(screen.getByText(/verify stocks/)).toBeInTheDocument();
    // group heading uses the friendly source label
    expect(screen.getAllByText(/daily brief/i).length).toBeGreaterThanOrEqual(1);
    // controls
    expect(screen.getByLabelText("search files")).toBeInTheDocument();
    expect(screen.getByLabelText("filter source")).toBeInTheDocument();
    expect(screen.getByLabelText("filter type")).toBeInTheDocument();
  });

  it("re-queries the API when the search text changes", async () => {
    vi.mocked(api.listFiles).mockResolvedValue(SAMPLE as never);
    render(<FilesBrowser />);
    await waitFor(() => expect(api.listFiles).toHaveBeenCalled());
    await userEvent.type(screen.getByLabelText("search files"), "notes");
    await waitFor(() => expect(vi.mocked(api.listFiles).mock.calls.some((c) => c[0]?.q === "notes")).toBe(true));
  });

  it("opens an in-pane preview when a file is clicked", async () => {
    vi.mocked(api.listFiles).mockResolvedValue(SAMPLE as never);
    render(<FilesBrowser />);
    await waitFor(() => expect(screen.getByText("notes.txt")).toBeInTheDocument());
    await userEvent.click(screen.getByText("notes.txt"));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
