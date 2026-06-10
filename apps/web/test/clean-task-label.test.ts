import { describe, expect, it } from "vitest";
import { cleanTaskLabel, isScheduledPrompt } from "@/lib/utils";

describe("cleanTaskLabel", () => {
  it("strips the [scheduled] tag and monotonic timestamp", () => {
    expect(
      cleanTaskLabel("[scheduled] Run your scheduled daily task. Current time: 677454.631"),
    ).toBe("Run your scheduled daily task.");
  });

  it("strips the ISO 'Now:' suffix used by the new scheduler prompt", () => {
    expect(
      cleanTaskLabel("[scheduled] Run your scheduled daily task. Now: 2026-06-09T23:30:00Z"),
    ).toBe("Run your scheduled daily task.");
  });

  it("leaves normal prompts alone", () => {
    expect(cleanTaskLabel("research NVDA earnings")).toBe("research NVDA earnings");
    expect(cleanTaskLabel(null)).toBe("");
  });
});

describe("isScheduledPrompt", () => {
  it("detects the [scheduled] tag", () => {
    expect(isScheduledPrompt("[scheduled] x")).toBe(true);
    expect(isScheduledPrompt("research X")).toBe(false);
    expect(isScheduledPrompt(undefined)).toBe(false);
  });
});
