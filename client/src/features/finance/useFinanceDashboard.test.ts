import { describe, expect, it } from "vitest";

import { financeTrendMonths } from "./useFinanceDashboard";

describe("financeTrendMonths", () => {
  it("returns exactly the selected month and its five preceding months", () => {
    expect(financeTrendMonths("2026-10")).toEqual([
      "2026-05",
      "2026-06",
      "2026-07",
      "2026-08",
      "2026-09",
      "2026-10",
    ]);
  });

  it("crosses year boundaries without adding future months", () => {
    expect(financeTrendMonths("2026-02")).toEqual([
      "2025-09",
      "2025-10",
      "2025-11",
      "2025-12",
      "2026-01",
      "2026-02",
    ]);
  });
});
