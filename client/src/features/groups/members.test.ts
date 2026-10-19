import { describe, expect, it } from "vitest";

import { memberDisplayName, shortAddress } from "./members";

const alex = `0x${"a".repeat(40)}`;
const sam = `0x${"b".repeat(40)}`;
const members = [
  { actor_address: alex, display_name: "Alex", active: true },
  { actor_address: sam, display_name: "Sam", active: true },
];

describe("group member labels", () => {
  it("finds a member's display name by wallet address", () => {
    expect(memberDisplayName(members, sam)).toBe("Sam");
    expect(memberDisplayName(members, `0x${"A".repeat(40)}`)).toBe("Alex");
  });

  it("returns null for a wallet outside the group", () => {
    expect(memberDisplayName(members, `0x${"c".repeat(40)}`)).toBeNull();
  });

  it("shortens wallet addresses for fallback display", () => {
    expect(shortAddress(alex)).toBe("0xaaaaaa…aaaaaa");
  });
});
