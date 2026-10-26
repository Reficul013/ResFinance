import { useCallback, useRef, useState } from "react";

export type GroupActionStatus = "idle" | "working" | "signing" | "saving";

export interface GroupActionSteps {
  sign<T>(signature: Promise<T>): Promise<T>;
}

export function useGroupAction() {
  const [error, setError] = useState<Error | null>(null);
  const [status, setStatus] = useState<GroupActionStatus>("idle");
  const running = useRef(false);

  const run = useCallback(
    async (action: (steps: GroupActionSteps) => Promise<void>) => {
      if (running.current) return;
      running.current = true;
      setError(null);
      setStatus("working");
      const steps: GroupActionSteps = {
        async sign(signature) {
          setStatus("signing");
          try {
            return await signature;
          } finally {
            setStatus("saving");
          }
        },
      };
      try {
        await action(steps);
      } catch (caught) {
        setError(
          caught instanceof Error
            ? caught
            : new Error("The group request failed."),
        );
      } finally {
        running.current = false;
        setStatus("idle");
      }
    },
    [],
  );

  return { error, status, busy: status !== "idle", run };
}

export type GroupAction = ReturnType<typeof useGroupAction>;
