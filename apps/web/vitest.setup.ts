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

  // jsdom has no EventSource; several tabs open SSE streams on mount.
  if (typeof (window as unknown as { EventSource?: unknown }).EventSource === "undefined") {
    (window as unknown as { EventSource: unknown }).EventSource = class {
      onmessage: ((e: unknown) => void) | null = null;
      onerror: ((e: unknown) => void) | null = null;
      close() {}
      addEventListener() {}
      removeEventListener() {}
    };
    (globalThis as unknown as { EventSource: unknown }).EventSource = (window as unknown as {
      EventSource: unknown;
    }).EventSource;
  }

  // Default fetch stub so any un-mocked direct fetch resolves to empty JSON
  // instead of throwing. Per-test mocks override this.
  if (typeof globalThis.fetch === "undefined") {
    (globalThis as unknown as { fetch: unknown }).fetch = () =>
      Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([]), text: () => Promise.resolve("") });
  }
}
