import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

// Unmount React trees and reset mocks between tests.
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

// jsdom lacks these; several components touch them.
if (typeof window !== "undefined") {
  window.matchMedia =
    window.matchMedia ||
    ((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    } as unknown as MediaQueryList));

  // Framer Motion / scroll-area probes.
  (window as unknown as { ResizeObserver: unknown }).ResizeObserver =
    (window as unknown as { ResizeObserver?: unknown }).ResizeObserver ||
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    };

  Element.prototype.scrollIntoView = Element.prototype.scrollIntoView || (() => {});
}
