import { describe, expect, it } from "vitest";

import { unlockErrorMessage } from "./popup-status";

describe("unlockErrorMessage", () => {
  it("uses a concise incorrect-password message for decryption failures", () => {
    expect(
      unlockErrorMessage(
        new Error("password or encrypted ResVault seed is invalid"),
      ),
    ).toBe("Incorrect Password");
    expect(
      unlockErrorMessage(
        new Error("ResVault password must be at least 12 characters"),
      ),
    ).toBe("Incorrect Password");
  });

  it("preserves operational errors", () => {
    expect(
      unlockErrorMessage(new Error("ResVault background is unavailable")),
    ).toBe("ResVault background is unavailable");
  });
});
