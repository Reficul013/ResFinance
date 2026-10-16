import { lazy, Suspense } from "react";
import { Navigate, NavLink, Route, Routes } from "react-router-dom";

import { AuthCard } from "../components/AuthCard";
import { StatusCard } from "../components/StatusCard";
import { ThemeToggle } from "../components/ThemeToggle";
import { useAuthentication } from "../features/auth/useAuthentication";
import { NotificationCenter } from "../features/insights/NotificationCenter";
import { usePlatformHealth } from "../features/platform/usePlatformHealth";

const FinanceDashboard = lazy(() =>
  import("../features/finance/FinanceDashboard").then((module) => ({
    default: module.FinanceDashboard,
  })),
);
const GroupsDashboard = lazy(() =>
  import("../features/groups/GroupsDashboard").then((module) => ({
    default: module.GroupsDashboard,
  })),
);
const CryptoDashboard = lazy(() =>
  import("../features/crypto/CryptoDashboard").then((module) => ({
    default: module.CryptoDashboard,
  })),
);
const InsightsDashboard = lazy(() =>
  import("../features/insights/InsightsDashboard").then((module) => ({
    default: module.InsightsDashboard,
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
      {!authenticated && <ThemeToggle />}
      {!authenticated && (
        <>
          <p className="eyebrow">Milestone 8 · Read-only insights</p>
          <h1>ResFinance</h1>
          <p className="lede">
            Connect the hardened ResVault extension to open your encrypted
            finance and groups dashboards. Your seed stays inside the extension.
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
        <>
          <div className="app-navigation">
            <nav className="dashboard-nav" aria-label="ResFinance dashboards">
              <NavLink to="/finance">Personal Finance</NavLink>
              <NavLink to="/groups">Friends &amp; Groups</NavLink>
              <NavLink to="/crypto">Crypto</NavLink>
              <NavLink to="/insights">Smart Insights</NavLink>
            </nav>
            <NotificationCenter accessToken={authentication.accessToken!} />
          </div>
          <Routes>
            <Route
              path="/finance"
              element={
                <Suspense
                  fallback={<RouteLoading text="Opening Personal Finance…" />}
                >
                  <FinanceDashboard accessToken={authentication.accessToken!} />
                </Suspense>
              }
            />
            <Route
              path="/groups"
              element={
                <Suspense
                  fallback={<RouteLoading text="Opening Friends & Groups…" />}
                >
                  <GroupsDashboard
                    accessToken={authentication.accessToken!}
                    actorAddress={authentication.actorAddress!}
                  />
                </Suspense>
              }
            />
            <Route
              path="/crypto"
              element={
                <Suspense fallback={<RouteLoading text="Opening Crypto…" />}>
                  <CryptoDashboard accessToken={authentication.accessToken!} />
                </Suspense>
              }
            />
            <Route
              path="/insights"
              element={
                <Suspense
                  fallback={<RouteLoading text="Opening Smart Insights…" />}
                >
                  <InsightsDashboard
                    accessToken={authentication.accessToken!}
                  />
                </Suspense>
              }
            />
            <Route path="*" element={<Navigate to="/finance" replace />} />
          </Routes>
        </>
      ) : (
        <StatusCard state={health.state} message={health.message} />
      )}
    </main>
  );
}

function RouteLoading({ text }: { text: string }) {
  return (
    <section className="dashboard-state" aria-live="polite">
      <span className="loading-orb" aria-hidden="true" />
      <h2>{text}</h2>
    </section>
  );
}
