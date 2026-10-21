import type { ReactNode } from "react";

import type { AuthenticationState } from "../features/auth/useAuthentication";
import { GitHubLink } from "./GitHubLink";
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
  const authenticated = state === "authenticated" && actorAddress !== null;
  const busy =
    state === "checking" || state === "locked" || state === "pending";
  return (
    <section className="auth-card" data-state={state} aria-live="polite">
      <div className="auth-session">
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
        <div className="auth-session-copy">
          <p className="auth-kicker">Wallet authentication</p>
          <h2>
            {authenticated ? (
              <button
                className="auth-brand-link"
                type="button"
                onClick={onLogout}
                title="Log out and return to the ResFinance welcome screen"
              >
                ResFinance
              </button>
            ) : (
              "Connect ResWallet"
            )}
          </h2>
          <p className="auth-message">
            {!authenticated && (
              <span className="auth-status-bulb" aria-hidden="true">
                💡
              </span>
            )}
            <span>{message}</span>
          </p>
          {(actorAddress ?? walletAddress) !== null && (
            <p className="wallet-identity">
              <span>Your Wallet Address:</span>
              {` `}
              <code className="wallet-address">
                {actorAddress ?? walletAddress}
              </code>
            </p>
          )}
        </div>
      </div>
      {authenticated && children}
      {authenticated ? (
        <div className="auth-actions">
          <GitHubLink />
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
        <div className="auth-connect-controls">
          <button
            className="auth-button"
            type="button"
            onClick={onConnect}
            disabled={busy || walletAddress === null}
          >
            {state === "pending" ? "Waiting for approval…" : "Connect wallet"}
          </button>
          <div className="auth-help">
            <button
              className="auth-help-button"
              type="button"
              aria-label="How to connect ResWallet"
              aria-describedby="reswallet-login-help"
            >
              <svg
                className="auth-help-icon"
                aria-hidden="true"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
                focusable="false"
              >
                <circle cx="12" cy="12" r="9" />
                <path d="M12 11v5" />
                <circle
                  cx="12"
                  cy="8"
                  r="0.85"
                  fill="currentColor"
                  stroke="none"
                />
              </svg>
            </button>
            <div
              className="auth-help-popover"
              id="reswallet-login-help"
              role="tooltip"
            >
              <strong>How to connect</strong>
              <ol>
                <li>
                  Install and enable the hardened ResWallet extension for wallet
                  authentication.
                </li>
                <li>Open ResWallet extension &amp; unlock your wallet.</li>
                <li>
                  Return here, select <b>Connect wallet</b>, then choose{` `}
                  <b>Approve &amp; Login</b>.
                </li>
              </ol>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
