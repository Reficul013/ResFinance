import type { AuthenticationState } from "../features/auth/useAuthentication";
import { ThemeToggle } from "./ThemeToggle";

interface AuthCardProps {
  state: AuthenticationState;
  message: string;
  walletAddress: string | null;
  actorAddress: string | null;
  onConnect(): void;
  onLogout(): void;
}

export function AuthCard({
  state,
  message,
  walletAddress,
  actorAddress,
  onConnect,
  onLogout,
}: AuthCardProps) {
  const authenticated = state === "authenticated";
  const busy = state === "checking" || state === "pending";
  return (
    <section className="auth-card" data-state={state} aria-live="polite">
      <div>
        <p className="auth-kicker">Wallet authentication</p>
        <h2>{authenticated ? "Session active" : "Connect ResVault"}</h2>
        <p className="auth-message">{message}</p>
        {(actorAddress ?? walletAddress) !== null && (
          <code className="wallet-address">
            {actorAddress ?? walletAddress}
          </code>
        )}
      </div>
      {authenticated ? (
        <div className="auth-actions">
          <button
            className="auth-button secondary"
            type="button"
            onClick={onLogout}
          >
            Log out
          </button>
          <ThemeToggle />
        </div>
      ) : (
        <button
          className="auth-button"
          type="button"
          onClick={onConnect}
          disabled={busy || walletAddress === null}
        >
          {state === "pending" ? "Waiting for approval…" : "Connect wallet"}
        </button>
      )}
    </section>
  );
}
