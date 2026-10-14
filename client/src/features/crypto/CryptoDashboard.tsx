import { useState, type FormEvent } from "react";

import type {
  CryptoOverview,
  PortfolioRecommendation,
} from "../../lib/api/client";
import { currentMonth, formatUsd, usdToMinorUnits } from "../finance/money";
import { CryptoChart } from "./CryptoChart";
import { useCryptoDashboard } from "./useCryptoDashboard";

type Asset = "BTC" | "ETH" | "SOL";
const ASSETS: Asset[] = ["BTC", "ETH", "SOL"];
const QUESTIONS = [
  ["time_horizon", "Investment time horizon", "Short", "Long"],
  ["loss_tolerance", "Comfort with temporary losses", "Low", "High"],
  ["income_stability", "Income stability", "Variable", "Stable"],
  ["liquidity_need", "Need for near-term access", "Low", "High"],
  ["investing_experience", "Investing experience", "New", "Experienced"],
] as const;

export function CryptoDashboard({ accessToken }: { accessToken: string }) {
  const [month, setMonth] = useState(currentMonth());
  const [asset, setAsset] = useState<Asset>("BTC");
  const dashboard = useCryptoDashboard(accessToken, month);

  if (dashboard.overview.isPending) {
    return (
      <DashboardState
        title="Building your crypto view…"
        text="Reading Finance savings, risk policy, and promoted forecast evidence."
      />
    );
  }
  if (dashboard.overview.isError) {
    return (
      <DashboardState
        title="Crypto analysis is unavailable."
        text={dashboard.overview.error.message}
        error
      />
    );
  }
  const overview = dashboard.overview.data;
  const displayed = dashboard.scenario.data ?? overview.recommendation;
  return (
    <div className="finance-dashboard crypto-dashboard">
      <section className="dashboard-header" aria-labelledby="crypto-title">
        <div>
          <p className="eyebrow">Milestone 7 · Risk-aware portfolio</p>
          <h1 id="crypto-title">Savings, translated into choices.</h1>
          <p className="lede">
            Explore a long-only BTC, ETH, and SOL allocation backed by your risk
            profile, Finance savings, and an explicitly promoted 15-day
            forecast.
          </p>
        </div>
        <label className="month-control">
          <span>Savings month</span>
          <input
            type="month"
            value={month}
            onChange={(event) => setMonth(event.target.value)}
          />
        </label>
      </section>

      <section className="summary-grid" aria-label="Crypto analysis summary">
        <Metric
          label="Default capital"
          value={formatUsd(overview.default_capital.minor_units)}
          note={overview.savings_formula_version}
        />
        <Metric
          label="Risk score"
          value={overview.risk_profile?.score.toString() ?? "Not set"}
          note="0 conservative · 100 growth"
        />
        <Metric
          label="Forecast"
          value={overview.forecast === null ? "Unavailable" : "15 days"}
          note={
            overview.forecast === null
              ? "No promoted model"
              : `As of ${new Date(overview.forecast.as_of_utc).toLocaleDateString()}`
          }
        />
        <Metric
          label="Allocation source"
          value={displayed?.source_kind === "scenario" ? "Scenario" : "Finance"}
          note="No trades are executed"
        />
      </section>

      <div className="dashboard-columns">
        <RiskQuestionnaire overview={overview} dashboard={dashboard} />
        <ScenarioPanel dashboard={dashboard} />
      </div>

      {overview.forecast === null ? (
        <section className="panel empty-forecast" role="status">
          <p className="section-kicker">Promotion gate holding</p>
          <h2>No forecast is eligible for portfolio use.</h2>
          <p>
            Milestone 6 did not promote its smoke candidate. This dashboard will
            remain evidence-safe until a model passes the immutable promotion
            criteria.
          </p>
        </section>
      ) : (
        <section className="panel" aria-labelledby="forecast-chart-title">
          <div className="section-heading compact">
            <div>
              <p className="section-kicker">Observed + forecast interval</p>
              <h2 id="forecast-chart-title">Price outlook</h2>
            </div>
            <div className="asset-switcher" aria-label="Chart asset">
              {ASSETS.map((value) => (
                <button
                  key={value}
                  className={value === asset ? "active" : ""}
                  type="button"
                  onClick={() => setAsset(value)}
                >
                  {value}
                </button>
              ))}
            </div>
          </div>
          <CryptoChart overview={overview} asset={asset} />
          <p className="panel-note">
            The P10–P90 range represents model uncertainty, not a guarantee.
          </p>
        </section>
      )}

      {displayed !== null && displayed !== undefined && (
        <AllocationPanel recommendation={displayed} />
      )}
      <details className="provenance-panel">
        <summary>Calculation and evidence provenance</summary>
        <div>
          <p>
            Finance calculation <code>{overview.savings_calculation_id}</code>{" "}
            references {overview.savings_source_event_ids.length} immutable
            event(s).
          </p>
          {overview.forecast !== null && (
            <p>
              Forecast <code>{overview.forecast.snapshot_id}</code> is
              authorized by promotion event{" "}
              <code>{overview.forecast.promotion_event_id}</code>.
            </p>
          )}
        </div>
      </details>
    </div>
  );
}

function RiskQuestionnaire({
  overview,
  dashboard,
}: {
  overview: CryptoOverview;
  dashboard: ReturnType<typeof useCryptoDashboard>;
}) {
  const existing = overview.risk_profile?.answers;
  const [answers, setAnswers] = useState<
    Record<(typeof QUESTIONS)[number][0], number>
  >({
    time_horizon: existing?.time_horizon ?? 2,
    loss_tolerance: existing?.loss_tolerance ?? 2,
    income_stability: existing?.income_stability ?? 2,
    liquidity_need: existing?.liquidity_need ?? 2,
    investing_experience: existing?.investing_experience ?? 2,
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    dashboard.riskProfile.mutate({
      idempotencyKey: crypto.randomUUID(),
      body: { answers, expected_version: overview.risk_projection_version },
    });
  }
  return (
    <section className="entry-panel" aria-labelledby="risk-title">
      <div className="section-heading">
        <div>
          <p className="section-kicker">Policy v1</p>
          <h2 id="risk-title">Risk questionnaire</h2>
        </div>
        {overview.risk_profile !== null && (
          <span className="freshness-pill">
            Score {overview.risk_profile.score}
          </span>
        )}
      </div>
      <form className="risk-form" onSubmit={submit}>
        {QUESTIONS.map(([key, label, low, high]) => (
          <label className="form-field" key={key}>
            <span>{label}</span>
            <select
              value={answers[key]}
              onChange={(event) =>
                setAnswers((current) => ({
                  ...current,
                  [key]: Number(event.target.value),
                }))
              }
            >
              {[0, 1, 2, 3, 4].map((value) => (
                <option value={value} key={value}>
                  {value} · {scaleLabel(value, low, high)}
                </option>
              ))}
            </select>
          </label>
        ))}
        <button
          className="primary-button"
          type="submit"
          disabled={dashboard.riskProfile.isPending}
        >
          {dashboard.riskProfile.isPending ? "Saving…" : "Save risk profile"}
        </button>
        {dashboard.riskProfile.isError && (
          <p className="form-error" role="alert">
            {dashboard.riskProfile.error.message}
          </p>
        )}
      </form>
    </section>
  );
}

function ScenarioPanel({
  dashboard,
}: {
  dashboard: ReturnType<typeof useCryptoDashboard>;
}) {
  const [amount, setAmount] = useState("1000");
  const [validationError, setValidationError] = useState<string | null>(null);
  function submit(event: FormEvent) {
    event.preventDefault();
    try {
      const cents = usdToMinorUnits(amount);
      setValidationError(null);
      dashboard.scenario.mutate({
        amount: { currency: "USD", minor_units: cents },
      });
    } catch (error) {
      setValidationError(
        error instanceof Error ? error.message : "Enter a valid USD amount.",
      );
    }
  }
  return (
    <section className="entry-panel" aria-labelledby="scenario-title">
      <p className="section-kicker">Read-only what-if</p>
      <h2 id="scenario-title">Analyze Another Amount</h2>
      <p className="panel-note">
        Change only this on-screen scenario. Finance savings and its source
        events are never updated.
      </p>
      <form className="scenario-form" onSubmit={submit}>
        <label className="form-field">
          <span>Scenario amount (USD)</span>
          <input
            type="number"
            min="0.01"
            step="0.01"
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
          />
        </label>
        <button
          className="primary-button"
          type="submit"
          disabled={dashboard.scenario.isPending}
        >
          {dashboard.scenario.isPending ? "Analyzing…" : "Analyze amount"}
        </button>
      </form>
      {dashboard.scenario.isError && (
        <p className="form-error" role="alert">
          {dashboard.scenario.error.message}
        </p>
      )}
      {validationError !== null && (
        <p className="form-error" role="alert">
          {validationError}
        </p>
      )}
      {dashboard.scenario.data !== undefined && (
        <p className="scenario-result">
          Scenario active:{" "}
          {formatUsd(dashboard.scenario.data.capital.minor_units)}. Your Finance
          default is unchanged.
        </p>
      )}
    </section>
  );
}

function AllocationPanel({
  recommendation,
}: {
  recommendation: PortfolioRecommendation;
}) {
  return (
    <section className="panel" aria-labelledby="allocation-title">
      <div className="section-heading compact">
        <div>
          <p className="section-kicker">Constrained recommendation</p>
          <h2 id="allocation-title">Portfolio allocation</h2>
        </div>
        <span className="freshness-pill">{recommendation.solver}</span>
      </div>
      <div className="allocation-grid">
        {recommendation.allocations.map((item) => (
          <article key={item.asset}>
            <span>{item.asset}</span>
            <strong>{formatUsd(item.amount.minor_units)}</strong>
            <small>
              {(Number(item.weight) * 100).toFixed(1)}% · cap{" "}
              {(Number(item.cap) * 100).toFixed(0)}%
            </small>
            <div className="allocation-track">
              <i style={{ width: `${Number(item.weight) * 100}%` }} />
            </div>
          </article>
        ))}
      </div>
      {recommendation.warnings.map((warning) => (
        <p className="panel-note" key={warning}>
          {warning}
        </p>
      ))}
    </section>
  );
}

function Metric({
  label,
  value,
  note,
}: {
  label: string;
  value: string;
  note: string;
}) {
  return (
    <article className="metric-card">
      <p>{label}</p>
      <strong>{value}</strong>
      <small>{note}</small>
    </article>
  );
}
function DashboardState({
  title,
  text,
  error = false,
}: {
  title: string;
  text: string;
  error?: boolean;
}) {
  return (
    <section
      className={`dashboard-state${error ? " error-state" : ""}`}
      role={error ? "alert" : "status"}
    >
      <span className="loading-orb" aria-hidden="true" />
      <h2>{title}</h2>
      <p>{text}</p>
    </section>
  );
}

function scaleLabel(value: number, low: string, high: string): string {
  if (value === 0) return low;
  if (value === 1) return `Leaning ${low.toLowerCase()}`;
  if (value === 2) return "Balanced";
  if (value === 3) return `Leaning ${high.toLowerCase()}`;
  return high;
}
