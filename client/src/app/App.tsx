import { AuthCard } from "../components/AuthCard";
import { StatusCard } from "../components/StatusCard";
import { ThemeToggle } from "../components/ThemeToggle";
import { useAuthentication } from "../features/auth/useAuthentication";
import { usePlatformHealth } from "../features/platform/usePlatformHealth";

export function App() {
  const health = usePlatformHealth();
  const authentication = useAuthentication();

  return (
    <main className="shell">
      <ThemeToggle />
      <p className="eyebrow">Milestone 2 · Wallet authentication</p>
      <h1>ResFinance</h1>
      <p className="lede">
        Connect the hardened ResVault extension. Your seed stays inside the
        extension, and every login requires a short-lived, origin-bound
        approval.
      </p>
      <AuthCard
        state={authentication.state}
        message={authentication.message}
        walletAddress={authentication.identity?.address ?? null}
        actorAddress={authentication.actorAddress}
        onConnect={() => void authentication.connect()}
        onLogout={() => void authentication.logout()}
      />
      <StatusCard state={health.state} message={health.message} />
    </main>
  );
}
