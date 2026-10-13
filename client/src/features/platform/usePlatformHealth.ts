import { useEffect, useState } from "react";

import type { PlatformState } from "../../components/StatusCard";
import { getHealth } from "../../lib/api/client";

interface PlatformHealthState {
  state: PlatformState;
  message: string;
}

export function usePlatformHealth(): PlatformHealthState {
  const [health, setHealth] = useState<PlatformHealthState>({
    state: "checking",
    message: "Checking the versioned API boundary…",
  });

  useEffect(() => {
    const controller = new AbortController();
    getHealth(controller.signal)
      .then((response) => {
        setHealth({
          state: "ready",
          message: `${response.service} is ready`,
        });
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setHealth({
            state: "error",
            message: "The local API is not reachable.",
          });
        }
      });
    return () => {
      controller.abort();
    };
  }, []);

  return health;
}
