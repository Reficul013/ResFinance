import { afterEach, describe, expect, it, vi } from "vitest";

import { queryInsights } from "./client";

describe("queryInsights", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("stops a stalled evidence request with a useful error", async () => {
    vi.useFakeTimers();
    vi.spyOn(globalThis, "fetch").mockImplementation(
      (_input, init) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener(
            "abort",
            () => reject(new DOMException("Aborted", "AbortError")),
            { once: true },
          );
        }),
    );

    const request = expect(
      queryInsights("access-token", {
        month: "2026-10",
        question: "How can I improve my savings?",
      }),
    ).rejects.toThrow("The evidence check took too long. Please try again.");

    await vi.advanceTimersByTimeAsync(30_000);
    await request;
  });
});
