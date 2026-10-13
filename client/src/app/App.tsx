import { StatusCard } from "../components/StatusCard";
import { usePlatformHealth } from "../features/platform/usePlatformHealth";

export function App() {
  const health = usePlatformHealth();

  return (
    <main className="shell">
      <p className="eyebrow">Milestone 1 · Platform foundation</p>
      <h1>ResFinance</h1>
      <p className="lede">
        The browser uses the generated <code>/api/v1</code> client boundary. It
        never connects directly to ResilientDB or ResContract.
      </p>
      <StatusCard state={health.state} message={health.message} />
    </main>
  );
}
