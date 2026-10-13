export type PlatformState = "checking" | "ready" | "error";

interface StatusCardProps {
  state: PlatformState;
  message: string;
}

export function StatusCard({ state, message }: StatusCardProps) {
  return (
    <section className="status-card" data-state={state} aria-live="polite">
      <span className="status-dot" aria-hidden="true" />
      <span>{message}</span>
    </section>
  );
}
