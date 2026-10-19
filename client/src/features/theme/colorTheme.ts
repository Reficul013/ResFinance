export type ColorTheme = "light" | "dark";

export const COLOR_THEME_STORAGE_KEY = "resfinance-color-theme";

export function resolveColorTheme(storedTheme: string | null): ColorTheme {
  if (storedTheme === "light" || storedTheme === "dark") {
    return storedTheme;
  }
  return "dark";
}

export function getPreferredColorTheme(): ColorTheme {
  return resolveColorTheme(
    window.localStorage.getItem(COLOR_THEME_STORAGE_KEY),
  );
}

export function applyColorTheme(theme: ColorTheme): void {
  document.documentElement.dataset.theme = theme;
  window.localStorage.setItem(COLOR_THEME_STORAGE_KEY, theme);
}

export function initializeColorTheme(): ColorTheme {
  const theme = getPreferredColorTheme();
  document.documentElement.dataset.theme = theme;
  return theme;
}

export function oppositeColorTheme(theme: ColorTheme): ColorTheme {
  return theme === "dark" ? "light" : "dark";
}
