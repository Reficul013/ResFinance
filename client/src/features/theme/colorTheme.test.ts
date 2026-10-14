import { describe, expect, it } from "vitest";

import { oppositeColorTheme, resolveColorTheme } from "./colorTheme";

describe("color theme", () => {
  it("uses a stored explicit preference before the system preference", () => {
    expect(resolveColorTheme("light", true)).toBe("light");
    expect(resolveColorTheme("dark", false)).toBe("dark");
  });

  it("falls back to the system preference", () => {
    expect(resolveColorTheme(null, true)).toBe("dark");
    expect(resolveColorTheme(null, false)).toBe("light");
  });

  it("toggles between the supported themes", () => {
    expect(oppositeColorTheme("dark")).toBe("light");
    expect(oppositeColorTheme("light")).toBe("dark");
  });
});
