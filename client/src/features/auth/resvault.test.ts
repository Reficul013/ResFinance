import { describe, expect, it } from "vitest";

import { hashParameters } from "./resvault";

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
});
