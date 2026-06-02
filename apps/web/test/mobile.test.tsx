import { describe, it, expect, vi, beforeAll } from "vitest";
import type { ComponentType } from "react";
import { render } from "@testing-library/react";

// Everything pending → tabs mount in their loading state at a phone viewport.
vi.mock("@/lib/api", () => ({
  api: new Proxy({}, { get: () => () => new Promise(() => {}) }),
  streamJobLog: () => () => {},
  streamChat: () => () => {},
}));
vi.mock("@/lib/activity", () => ({ subscribeToActivity: () => () => {} }));
vi.mock("next/navigation", () => ({ usePathname: () => "/" }));
vi.mock("@/components/network-graph", () => ({ NetworkGraph: () => <div /> }));

import MeshPage from "@/app/page";
import NetworkPage from "@/app/network/page";
import AnalyticsPage from "@/app/analytics/page";
import JobsPage from "@/app/jobs/page";
import ArtifactsPage from "@/app/artifacts/page";
import DailyPage from "@/app/daily/page";
import CalendarPage from "@/app/calendar/page";

beforeAll(() => {
  Object.defineProperty(window, "innerWidth", { writable: true, configurable: true, value: 375 });
  Object.defineProperty(window, "innerHeight", { writable: true, configurable: true, value: 667 });
});

const tabs: Array<[string, ComponentType]> = [
  ["Mesh", MeshPage],
  ["Network", NetworkPage],
  ["Analytics", AnalyticsPage],
  ["Jobs", JobsPage],
  ["Artifacts", ArtifactsPage],
  ["Daily", DailyPage],
  ["Calendar", CalendarPage],
];

describe("mobile viewport (375px) — every tab renders", () => {
  it.each(tabs)("%s mounts on mobile without throwing", (_label, Page) => {
    const { container } = render(<Page />);
    expect(container.firstChild).toBeTruthy();
    expect(container.textContent).not.toContain("undefined");
  });
});
