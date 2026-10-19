import { useCallback, useState } from "react";

export function useGroupAction() {
  const [error, setError] = useState<Error | null>(null);
  const run = useCallback(async (action: () => Promise<void>) => {
    setError(null);
    try {
      await action();
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught
          : new Error("The group request failed."),
      );
    }
  }, []);
  return { error, run };
}
