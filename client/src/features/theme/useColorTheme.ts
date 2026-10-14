import { useCallback, useState } from "react";

import {
  applyColorTheme,
  getPreferredColorTheme,
  oppositeColorTheme,
  type ColorTheme,
} from "./colorTheme";

export function useColorTheme() {
  const [theme, setTheme] = useState<ColorTheme>(getPreferredColorTheme);

  const toggleTheme = useCallback(() => {
    setTheme((currentTheme) => {
      const nextTheme = oppositeColorTheme(currentTheme);
      applyColorTheme(nextTheme);
      return nextTheme;
    });
  }, []);

  return { theme, toggleTheme };
}
