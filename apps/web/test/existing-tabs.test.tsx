import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// All API calls hang (pending) → every page sits in its loading state, which is
// the cleanest way to assert "renders without throwing" for the existing tabs
// (they already ship their own empty/error branches; covered functionally in app).
vi.mock("@/lib/api", () => ({
  api: new Proxy({}, { get: () => () => new Promise(() => {}) }),
  streamJobLog: () => () => {},
  streamChat: () => () => {},
}));
vi.mock("@/lib/activity", () => ({ subscribeToActivity: () => () => {} }));
vi.mock("next/navigation", () => ({ usePathname: () => "/" }));
// React Flow needs a real layout engine; stub the graph so the Network shell renders.
vi.mock("@/components/network-graph", () => ({ NetworkGraph: () => <div data-testid="network-graph" /> }));

import MeshPage from "@/app/page";
import NetworkPage from "@/app/network/page";
import AnalyticsPage from "@/app/analytics/page";
import JobsPage from "@/app/jobs/page";
import ArtifactsPage from "@/app/artifacts/page";

const pages: Array<[string, () => JSX.Element]> = [
  ["Mesh", MeshPage],
  ["Network", NetworkPage],
  ["Analytics", AnalyticsPage],
  ["Jobs", JobsPage],
  ["Artifacts", ArtifactsPage],
];

describe("existing tabs render without throwing", () => {
  it.each(pages)("%s mounts and shows the nav", (_label, Page) => {
    const { container } = render(<Page />);
    // Nav present (proves the page shell mounted).
    expect(screen.getAllByText("Mesh").length).toBeGreaterThan(0);
    // No crash text / raw undefined leaked into the DOM.
    expect(container.textContent).not.toContain("undefined");
  });
});
