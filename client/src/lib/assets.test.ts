import { describe, expect, it } from "vitest";

import { CRYPTO_ASSETS, isCryptoAsset } from "./assets";

describe("crypto asset boundary", () => {
  it("accepts exactly BTC, ETH, and SOL", () => {
    expect(CRYPTO_ASSETS).toEqual(["BTC", "ETH", "SOL"]);
    expect(isCryptoAsset("BTC")).toBe(true);
    expect(isCryptoAsset("DOGE")).toBe(false);
  });
});
