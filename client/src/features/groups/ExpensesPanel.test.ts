import { describe, expect, it } from "vitest";

import { formatExpenseDate, newestFirst, previewShares } from "./ExpensesPanel";

describe("expense history", () => {
  it("lists the newest expense date first", () => {
    expect(
      newestFirst([
        { id: "dinner", occurred_on: "2026-10-18" },
        { id: "taxi", occurred_on: "2026-10-19" },
        { id: "rent", occurred_on: "2026-10-01" },
      ]).map((item) => item.id),
    ).toEqual(["taxi", "dinner", "rent"]);
  });

  it("puts the most recently added expense first on the same date", () => {
    expect(
      newestFirst([
        { id: "lunch", occurred_on: "2026-10-19" },
        { id: "coffee", occurred_on: "2026-10-19" },
      ]).map((item) => item.id),
    ).toEqual(["coffee", "lunch"]);
  });

  it("keeps eight shares on the card and counts the rest", () => {
    const eight = ["a", "b", "c", "d", "e", "f", "g", "h"];
    expect(previewShares(eight)).toEqual({ visible: eight, hiddenCount: 0 });
    expect(previewShares([...eight, "i", "j"])).toEqual({
      visible: eight,
      hiddenCount: 2,
    });
  });

  it("formats the calendar date without shifting it by time zone", () => {
    expect(formatExpenseDate("2026-10-19")).toBe("Oct 19, 2026");
    expect(formatExpenseDate("2026-01-01")).toBe("Jan 1, 2026");
  });
});
