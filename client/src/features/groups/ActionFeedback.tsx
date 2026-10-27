import type { GroupAction } from "./useGroupAction";

export function ActionFeedback({ action }: { action: GroupAction }) {
  if (action.status === "signing")
    return (
      <p className="form-status" role="status">
        <span className="loading-orb" aria-hidden="true" />
        Waiting for your approval in ResWallet. If no ResWallet window appeared,
        check behind this browser window, or reload the page and try again.
      </p>
    );
  if (action.status === "saving")
    return (
      <p className="form-status" role="status">
        <span className="loading-orb" aria-hidden="true" />
        Saving to the group…
      </p>
    );
  return action.error === null ? null : (
    <p className="form-error" role="alert">
      {errorMessage(action.error)}
    </p>
  );
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "The group request failed.";
}
