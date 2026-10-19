import type { ReactNode } from "react";

import type { AuthenticationState } from "../features/auth/useAuthentication";
import { ThemeToggle } from "./ThemeToggle";

interface AuthCardProps {
  state: AuthenticationState;
  message: string;
  walletAddress: string | null;
  actorAddress: string | null;
  children?: ReactNode;
  actions?: ReactNode;
  onConnect(): void;
  onLogout(): void;
}

export function AuthCard({
  state,
  message,
  walletAddress,
  actorAddress,
  children,
  actions,
  onConnect,
  onLogout,
}: AuthCardProps) {
  const authenticated = state === "authenticated";
  const busy = state === "checking" || state === "pending";
  return (
    <section className="auth-card" data-state={state} aria-live="polite">
      <div className="auth-session">
        {authenticated && (
          <img
            className="auth-brand-logo"
            src="/favicon.png"
            alt=""
            aria-hidden="true"
          />
        )}
        <div className="auth-session-copy">
          <p className="auth-kicker">Wallet authentication</p>
          <h2>{authenticated ? "ResFinance" : "Connect ResVault"}</h2>
          <p className="auth-message">{message}</p>
          {(actorAddress ?? walletAddress) !== null && (
            <code className="wallet-address">
              {actorAddress ?? walletAddress}
            </code>
          )}
        </div>
      </div>
      {authenticated && children}
      {authenticated ? (
        <div className="auth-actions">
          <ThemeToggle />
          {actions}
          <button
            className="auth-button secondary"
            type="button"
            onClick={onLogout}
            aria-label="Log out"
            title="Log out"
          >
            <svg
              className="auth-action-icon"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
              <path d="m16 17 5-5-5-5" />
              <path d="M21 12H9" />
            </svg>
          </button>
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
