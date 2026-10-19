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
        <span className="theme-slider-icon">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            aria-hidden="true"
          >
            <circle cx="12" cy="12" r="4" />
            <path d="M12 2v2M12 20v2M4.93 4.93l1.42 1.42M17.65 17.65l1.42 1.42M2 12h2M20 12h2M4.93 19.07l1.42-1.42M17.65 6.35l1.42-1.42" />
          </svg>
        </span>
        <span className="theme-slider-icon">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79Z" />
          </svg>
        </span>
        <span className="theme-slider-thumb" />
      </span>
    </button>
  );
}
