import { describe, expect, it } from "vitest";

import { oppositeColorTheme, resolveColorTheme } from "./colorTheme";

describe("color theme", () => {
  it("uses a stored explicit preference", () => {
    expect(resolveColorTheme("light")).toBe("light");
    expect(resolveColorTheme("dark")).toBe("dark");
  });

  it("defaults to dark mode when no preference is stored", () => {
    expect(resolveColorTheme(null)).toBe("dark");
    expect(resolveColorTheme("unsupported")).toBe("dark");
  });

  it("toggles between the supported themes", () => {
    expect(oppositeColorTheme("dark")).toBe("light");
    expect(oppositeColorTheme("light")).toBe("dark");
  });
});
