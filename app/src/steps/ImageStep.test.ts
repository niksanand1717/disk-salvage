import { describe, expect, it } from "vitest";

import { suggestedImageName } from "./ImageStep";

describe("suggestedImageName", () => {
  const day = new Date("2026-10-12T10:00:00Z");

  it("uses the drive model and the date", () => {
    expect(suggestedImageName({ path: "x", label: "SanDisk Ultra — 59.48 GB", isDrive: true, size: 1 }, day))
      .toBe("SanDisk Ultra 2026-10-12.img");
  });

  it("drops characters Windows does not allow in file names", () => {
    expect(suggestedImageName({ path: "x", label: 'Gen/eric: "USB" — 8 GB', isDrive: true, size: 1 }, day))
      .toBe("Generic USB 2026-10-12.img");
    expect(suggestedImageName({ path: "x", label: "", isDrive: true, size: 1 }, day)).toBe("drive 2026-10-12.img");
  });
});
