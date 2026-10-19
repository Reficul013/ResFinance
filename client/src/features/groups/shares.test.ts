import { describe, expect, it } from "vitest";

import { parseShares } from "./shares";

const alex = `0x${"a".repeat(40)}`;
const sam = `0x${"b".repeat(40)}`;

describe("group share parsing", () => {
  it("parses wallet=amount lines into integer cents", () => {
    expect(parseShares(`${alex}=10.00\n\n  0x${"B".repeat(40)} = 50 `)).toEqual(
      { [alex]: 1000, [sam]: 5000 },
    );
  });

  it("rejects malformed lines with readable messages", () => {
    expect(() => parseShares(`${alex} 10`)).toThrow(
      "Each share must use wallet=amount",
    );
    expect(() => parseShares("0x123=10")).toThrow(
      "A share has an invalid wallet address",
    );
    expect(() => parseShares(`${alex}=10\n${alex}=5`)).toThrow(
      "Each wallet may appear only once",
    );
    expect(() => parseShares("   \n")).toThrow(
      "At least one share is required",
    );
  });

  it("rejects zero-value placeholder shares", () => {
    expect(() => parseShares(`${alex}=0.00`)).toThrow(
      "Amount must be greater than $0.00.",
    );
  });
});
