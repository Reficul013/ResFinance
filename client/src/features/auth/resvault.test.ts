import { describe, expect, it } from "vitest";

import {
  formatIntentTimestamp,
  hashParameters,
  parseWalletStatusNotice,
} from "./resvault";

describe("ResVault page contract", () => {
  it("hashes challenge parameters exactly like the extension and backend", async () => {
    await expect(
      hashParameters({
        challenge: "challenge-value-cross-language",
        origin: "https://app.resfinance.local",
      }),
    ).resolves.toBe(
      "6216c467286569fc1d5ac542de67d940dcc585a7b0811c142a464bbf75c19eac",
    );
  });

  it("uses whole-second UTC timestamps for cross-language signatures", () => {
    expect(formatIntentTimestamp(new Date("2026-10-15T10:43:12.987Z"))).toBe(
      "2026-10-15T10:43:12Z",
    );
  });

  it("accepts only a complete public wallet-status notification", () => {
    expect(
      parseWalletStatusNotice({
        source: "resvault",
        version: 1,
        type: "STATUS_CHANGED",
        status: {
          exists: true,
          unlocked: true,
          identity: {
            public_key: "public-key",
            address: `0x${"a".repeat(40)}`,
          },
        },
      }),
    ).toMatchObject({ status: { exists: true, unlocked: true } });
    expect(
      parseWalletStatusNotice({
        source: "resvault",
        version: 1,
        type: "STATUS_CHANGED",
        status: { exists: true, unlocked: "yes", identity: null },
      }),
    ).toBeNull();
  });
});
