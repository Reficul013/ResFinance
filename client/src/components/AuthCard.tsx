import type { ReactNode } from "react";
import { Link } from "react-router-dom";

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
          <>
            <img
              className="auth-brand-logo auth-brand-logo-light"
              src="/favicon.png"
              alt=""
              aria-hidden="true"
            />
            <img
              className="auth-brand-logo auth-brand-logo-dark"
              src="/favicon-dark.png"
              alt=""
              aria-hidden="true"
            />
          </>
        )}
        <div className="auth-session-copy">
          <p className="auth-kicker">Wallet authentication</p>
          <h2>
            {authenticated ? (
              <Link
                className="auth-brand-link"
                to="/"
                title="Go to ResFinance main screen"
              >
                ResFinance
              </Link>
            ) : (
              "Connect ResVault"
            )}
          </h2>
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
          <a
            className="auth-button secondary"
            href="https://github.com/haseebshaik00/ResFinance"
            target="_blank"
            rel="noreferrer"
            aria-label="Open ResFinance repository on GitHub"
            title="GitHub"
          >
            <svg
              className="auth-action-icon github-icon"
              viewBox="0 0 24 24"
              width="28"
              height="28"
              fill="currentColor"
              aria-hidden="true"
              style={{ minWidth: 28, minHeight: 28 }}
            >
              <path d="M12 2C6.48 2 2 6.58 2 12.23c0 4.52 2.87 8.35 6.84 9.71.5.1.68-.22.68-.49 0-.24-.01-1.05-.02-1.9-2.78.62-3.37-1.21-3.37-1.21-.45-1.18-1.11-1.49-1.11-1.49-.91-.64.07-.62.07-.62 1 .07 1.53 1.06 1.53 1.06.89 1.57 2.34 1.11 2.91.85.09-.67.35-1.11.63-1.37-2.22-.26-4.56-1.14-4.56-5.06 0-1.12.39-2.03 1.03-2.75-.1-.26-.45-1.3.1-2.71 0 0 .84-.28 2.75 1.05A9.3 9.3 0 0 1 12 6.11a9.3 9.3 0 0 1 2.5.35c1.91-1.33 2.75-1.05 2.75-1.05.55 1.41.2 2.45.1 2.71.64.72 1.03 1.63 1.03 2.75 0 3.93-2.34 4.79-4.57 5.04.36.32.68.94.68 1.9 0 1.37-.01 2.47-.01 2.81 0 .27.18.6.69.49A10.25 10.25 0 0 0 22 12.23C22 6.58 17.52 2 12 2Z" />
            </svg>
          </a>
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
