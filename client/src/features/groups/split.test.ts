import { describe, expect, it } from "vitest";

import {
  applyEqualSplit,
  buildShares,
  equalShares,
  minorUnitsToAmount,
  splitProgress,
  type SplitRow,
} from "./split";

const alex = `0x${"a".repeat(40)}`;
const sam = `0x${"b".repeat(40)}`;
const priya = `0x${"c".repeat(40)}`;

function rows(
  overrides: Partial<Record<string, Partial<SplitRow>>> = {},
): SplitRow[] {
  return [
    { address: alex, name: "Alex", included: true, amount: "" },
    { address: sam, name: "Sam", included: true, amount: "" },
    { address: priya, name: "Priya", included: true, amount: "" },
  ].map((row) => ({ ...row, ...overrides[row.address] }));
}

describe("group split building", () => {
  it("builds integer-cent shares for only the included members", () => {
    expect(
      buildShares(
        "90.00",
        rows({
          [alex]: { amount: "30" },
          [sam]: { amount: "60.00" },
          [priya]: { included: false, amount: "15" },
        }),
        alex,
      ),
    ).toEqual({
      amountMinorUnits: 9000,
      shares: { [alex]: 3000, [sam]: 6000 },
    });
  });

  it("allows the payer to be left out of the split", () => {
    expect(
      buildShares(
        "60",
        rows({
          [alex]: { included: false },
          [sam]: { amount: "30" },
          [priya]: { amount: "30" },
        }),
        alex,
      ).shares,
    ).toEqual({ [sam]: 3000, [priya]: 3000 });
  });

  it("explains a missing or unbalanced split", () => {
    expect(() => buildShares("", rows(), alex)).toThrow(/^Total amount: /);
    expect(() =>
      buildShares(
        "60",
        rows({
          [alex]: { included: false },
          [sam]: { included: false },
          [priya]: { included: false },
        }),
        alex,
      ),
    ).toThrow("Choose at least one member to split with.");
    expect(() =>
      buildShares(
        "60",
        rows({
          [alex]: { amount: "60" },
          [sam]: { included: false },
          [priya]: { included: false },
        }),
        alex,
      ),
    ).toThrow("Include at least one other member.");
    expect(() =>
      buildShares(
        "60",
        rows({ [alex]: { amount: "30" }, [sam]: { amount: "0.00" } }),
        alex,
      ),
    ).toThrow("Sam's share: Amount must be greater than $0.00.");
    expect(() =>
      buildShares(
        "60",
        rows({
          [alex]: { amount: "20" },
          [sam]: { amount: "20" },
          [priya]: { amount: "10" },
        }),
        alex,
      ),
    ).toThrow(
      "Shares add up to $50.00, but the total is $60.00. Assign the remaining $10.00.",
    );
    expect(() =>
      buildShares(
        "60",
        rows({
          [alex]: { amount: "30" },
          [sam]: { amount: "30" },
          [priya]: { amount: "5" },
        }),
        alex,
      ),
    ).toThrow(
      "Shares add up to $65.00, which is $5.00 more than the total of $60.00.",
    );
  });
});

describe("equal splits", () => {
  it("divides the total evenly between included members", () => {
    expect(equalShares(9000, [alex, sam, priya], alex)).toEqual({
      [alex]: 3000,
      [sam]: 3000,
      [priya]: 3000,
    });
  });

  it("gives leftover cents to the payer first", () => {
    expect(equalShares(1000, [alex, sam, priya], sam)).toEqual({
      [sam]: 334,
      [alex]: 333,
      [priya]: 333,
    });
    expect(equalShares(1002, [alex, sam, priya], sam)).toEqual({
      [sam]: 334,
      [alex]: 334,
      [priya]: 334,
    });
  });

  it("gives leftover cents in list order when the payer is not included", () => {
    expect(equalShares(1001, [sam, priya], alex)).toEqual({
      [sam]: 501,
      [priya]: 500,
    });
  });

  it("fills only included rows and builds shares that add up exactly", () => {
    const split = applyEqualSplit(
      "10.01",
      rows({ [priya]: { included: false, amount: "99" } }),
      alex,
    );
    expect(split.map((row) => row.amount)).toEqual(["5.01", "5.00", ""]);
    expect(buildShares("10.01", split, alex).shares).toEqual({
      [alex]: 501,
      [sam]: 500,
    });
  });

  it("leaves amounts blank until the total is valid", () => {
    expect(
      applyEqualSplit("abc", rows(), alex).map((row) => row.amount),
    ).toEqual(["", "", ""]);
  });

  it("formats cents as an editable amount", () => {
    expect(minorUnitsToAmount(501)).toBe("5.01");
    expect(minorUnitsToAmount(5)).toBe("0.05");
    expect(minorUnitsToAmount(123456)).toBe("1234.56");
  });
});

describe("group split progress", () => {
  it("tracks assigned and remaining cents while typing", () => {
    expect(
      splitProgress(
        "60",
        rows({ [alex]: { amount: "20" }, [sam]: { amount: "abc" } }),
      ),
    ).toEqual({
      totalMinorUnits: 6000,
      assignedMinorUnits: 2000,
      remainingMinorUnits: 4000,
    });
  });

  it("ignores excluded members and reports overspend as negative", () => {
    expect(
      splitProgress(
        "60",
        rows({
          [alex]: { amount: "50" },
          [sam]: { amount: "20" },
          [priya]: { included: false, amount: "100" },
        }),
      ).remainingMinorUnits,
    ).toBe(-1000);
  });

  it("has no remaining amount until the total is valid", () => {
    expect(splitProgress("", rows({ [alex]: { amount: "5" } }))).toEqual({
      totalMinorUnits: null,
      assignedMinorUnits: 500,
      remainingMinorUnits: null,
    });
  });
});
