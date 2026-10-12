import { describe, expect, it } from "vitest";

import { duration, explainError, human, percent, progressText } from "./format";

describe("format", () => {
  it("formats sizes", () => {
    expect(human(null)).toBe("?");
    expect(human(2048)).toBe("2 KB");
    expect(human(5 * 1024 ** 2)).toBe("5.0 MB");
    expect(human(64 * 1024 ** 3)).toBe("64.00 GB");
  });

  it("formats durations", () => {
    expect(duration(42)).toBe("42s");
    expect(duration(125)).toBe("2m 05s");
    expect(duration(3 * 3600 + 7 * 60)).toBe("3h 07m");
    expect(duration(null)).toBe("");
  });

  it("describes progress", () => {
    const p = { phase: "scanning", done: 1024 ** 3, total: 4 * 1024 ** 3, unit: "bytes" as const,
                rate: 50 * 1024 ** 2, eta: 90 };
    expect(percent(p)).toBe(25);
    expect(progressText(p)).toBe("1.00 GB of 4.00 GB · 50.0 MB/s · about 1m 30s left");
  });

  it("explains access errors per platform", () => {
    expect(explainError({ type: "AccessDenied", message: "x" }, "win32")).toContain("Run as administrator");
    expect(explainError({ type: "AccessDenied", message: "x" }, "linux")).toContain("sudo");
    expect(explainError({ type: "OutOfSpace", message: "only 1 GB free" }, "linux")).toBe("only 1 GB free");
  });
});
