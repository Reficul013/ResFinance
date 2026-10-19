import { useColorTheme } from "../features/theme/useColorTheme";

export function ThemeToggle() {
  const { theme, toggleTheme } = useColorTheme();
  const nextTheme = theme === "dark" ? "light" : "dark";
  const nextThemeLabel = nextTheme === "dark" ? "Dark Mode" : "Light Mode";

  return (
    <button
      className="theme-toggle"
      type="button"
      data-theme={theme}
      onClick={toggleTheme}
      aria-label={`Switch to ${nextThemeLabel}`}
      aria-pressed={theme === "dark"}
      title={`Switch to ${nextThemeLabel}`}
    >
      <span className="theme-slider-track" aria-hidden="true">
        <span className="theme-slider-icon">☀︎</span>
        <span className="theme-slider-icon">☾</span>
        <span className="theme-slider-thumb" />
      </span>
    </button>
  );
}
