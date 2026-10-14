import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { AuthCard } from "../components/AuthCard";
import { StatusCard } from "../components/StatusCard";
import { ThemeToggle } from "../components/ThemeToggle";
import { useAuthentication } from "../features/auth/useAuthentication";
import { usePlatformHealth } from "../features/platform/usePlatformHealth";

const FinanceDashboard = lazy(() =>
  import("../features/finance/FinanceDashboard").then((module) => ({
    default: module.FinanceDashboard,
  })),
);

export function App() {
  const health = usePlatformHealth();
  const authentication = useAuthentication();
  const authenticated =
    authentication.state === "authenticated" &&
    authentication.accessToken !== null;

  return (
    <main className={authenticated ? "app-shell" : "shell"}>
      <ThemeToggle />
      {!authenticated && (
        <>
          <p className="eyebrow">Milestone 3 · Personal Finance</p>
          <h1>ResFinance</h1>
          <p className="lede">
            Connect the hardened ResVault extension to open your encrypted
            personal-finance dashboard. Your seed stays inside the extension.
          </p>
        </>
      )}
      <AuthCard
        state={authentication.state}
        message={authentication.message}
        walletAddress={authentication.identity?.address ?? null}
        actorAddress={authentication.actorAddress}
        onConnect={() => void authentication.connect()}
        onLogout={() => void authentication.logout()}
      />
      {authenticated ? (
        <Routes>
          <Route
            path="/finance"
            element={
              <Suspense
                fallback={
                  <section className="dashboard-state" aria-live="polite">
                    <span className="loading-orb" aria-hidden="true" />
                    <h2>Opening Personal Finance…</h2>
                  </section>
                }
              >
                <FinanceDashboard accessToken={authentication.accessToken!} />
              </Suspense>
            }
          />
          <Route path="*" element={<Navigate to="/finance" replace />} />
        </Routes>
      ) : (
        <StatusCard state={health.state} message={health.message} />
      )}
    </main>
  );
}
