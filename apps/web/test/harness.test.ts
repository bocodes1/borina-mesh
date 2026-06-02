import { describe, it, expect } from "vitest";

describe("vitest harness", () => {
  it("runs and has jsdom", () => {
    expect(typeof window).toBe("object");
    expect(1 + 1).toBe(2);
  });
});
