import { useColorTheme } from "../features/theme/useColorTheme";

export function ThemeToggle() {
  const { theme, toggleTheme } = useColorTheme();
  const nextTheme = theme === "dark" ? "light" : "dark";

  return (
    <button
      className="theme-toggle"
      type="button"
      onClick={toggleTheme}
      aria-label={`Switch to ${nextTheme} mode`}
    >
      <span className="theme-toggle-icon" aria-hidden="true">
        {theme === "dark" ? "☀︎" : "☾"}
      </span>
      <span className="theme-toggle-label">{nextTheme} mode</span>
    </button>
  );
}
