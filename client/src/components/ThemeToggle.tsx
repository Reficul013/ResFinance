import { useColorTheme } from "../features/theme/useColorTheme";

export function ThemeToggle() {
  const { theme, toggleTheme } = useColorTheme();
  const nextTheme = theme === "dark" ? "light" : "dark";
  const nextThemeLabel = nextTheme === "dark" ? "Dark Mode" : "Light Mode";

  return (
    <button
      className="theme-toggle"
      type="button"
      onClick={toggleTheme}
      aria-label={`Switch to ${nextThemeLabel}`}
    >
      <span className="theme-toggle-icon" aria-hidden="true">
        {theme === "dark" ? "☀︎" : "☾"}
      </span>
      <span className="theme-toggle-label">{nextThemeLabel}</span>
    </button>
  );
}
