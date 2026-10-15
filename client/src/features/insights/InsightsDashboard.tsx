import { useState, type FormEvent } from "react";

import type { InsightResponse } from "../../lib/api/client";
import { currentMonth } from "../finance/money";
import { useInsightsDashboard } from "./useInsightsDashboard";

export function InsightsDashboard({ accessToken }: { accessToken: string }) {
  const [month, setMonth] = useState(currentMonth());
  const [question, setQuestion] = useState("How can I improve my savings?");
  const dashboard = useInsightsDashboard(accessToken, month);

  if (dashboard.overview.isPending) {
    return <DashboardState title="Assembling authorized facts…" />;
  }
  if (dashboard.overview.isError) {
    return (
      <DashboardState
        title="Smart Savings Insights are unavailable."
        text={dashboard.overview.error.message}
        error
      />
    );
  }
  const response = dashboard.query.data ?? dashboard.overview.data.insight;

  function submit(event: FormEvent) {
    event.preventDefault();
    dashboard.query.mutate(question);
  }

  function ask(value: string) {
    setQuestion(value);
    dashboard.query.mutate(value);
  }

  return (
    <div className="finance-dashboard insights-dashboard">
      <section className="dashboard-header" aria-labelledby="insights-title">
        <div>
          <p className="eyebrow">Milestone 8 · Evidence-linked guidance</p>
          <h1 id="insights-title">Smart Savings Insights</h1>
          <p className="lede">
            Ask about your recorded savings, budgets, obligations, and crypto
            analysis. Answers are assembled only from facts authorized for your
            wallet.
          </p>
        </div>
        <label className="month-control">
          <span>Insight month</span>
          <input
            type="month"
            value={month}
            onChange={(event) => setMonth(event.target.value)}
          />
        </label>
      </section>

      <section className="insight-composer panel" aria-labelledby="ask-title">
        <div className="section-heading compact">
          <div>
            <p className="section-kicker">Read-only assistant</p>
            <h2 id="ask-title">Ask about your evidence</h2>
          </div>
          <span className={`generation-pill ${response.mode}`}>
            {modeLabel(response.mode)}
          </span>
        </div>
        <form onSubmit={submit}>
          <label className="form-field">
            <span>Question</span>
            <textarea
              value={question}
              maxLength={500}
              rows={3}
              onChange={(event) => setQuestion(event.target.value)}
            />
          </label>
          <button
            className="primary-button"
            disabled={dashboard.query.isPending}
          >
            {dashboard.query.isPending ? "Checking evidence…" : "Explain"}
          </button>
        </form>
        {dashboard.query.isError && (
          <p className="form-error" role="alert">
            {dashboard.query.error.message}
          </p>
        )}
      </section>

      <InsightResult response={response} onAsk={ask} />

      <details className="provenance-panel">
        <summary>Assistant boundary and model provenance</summary>
        <div>
          <p>
            Fact bundle <code>{dashboard.overview.data.fact_bundle_id}</code>
          </p>
          <p>
            Model <code>{response.model_id}</code> at revision{" "}
            <code>{response.model_revision.slice(0, 12)}</code>. The model may
            rank facts; final claims are rendered from validated evidence.
          </p>
          <p>
            This path has no write, ResVault, ResContract, trading, or direct
            ResilientDB capability.
          </p>
        </div>
      </details>
    </div>
  );
}

function InsightResult({
  response,
  onAsk,
}: {
  response: InsightResponse;
  onAsk(question: string): void;
}) {
  return (
    <section
      className={`insight-result panel${response.refused ? " refusal" : ""}`}
      aria-live="polite"
    >
      <p className="section-kicker">
        {response.refused ? "Request safely declined" : "Evidence-bound answer"}
      </p>
      <h2>{response.summary}</h2>
      {response.evidence.length > 0 && (
        <div className="evidence-grid" aria-label="Evidence used">
          {response.evidence.map((item) => (
            <article key={item.fact_id}>
              <span>{item.topic}</span>
              <p>{item.statement}</p>
              <small>
                {item.source_kind} · {item.source_ids.length} source reference
                {item.source_ids.length === 1 ? "" : "s"}
              </small>
            </article>
          ))}
        </div>
      )}
      <ul className="caveat-list">
        {response.caveats.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
      {response.follow_up_questions.length > 0 && (
        <div className="follow-up-row" aria-label="Suggested questions">
          {response.follow_up_questions.map((item) => (
            <button type="button" key={item} onClick={() => onAsk(item)}>
              {item}
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

function DashboardState({
  title,
  text,
  error = false,
}: {
  title: string;
  text?: string;
  error?: boolean;
}) {
  return (
    <section
      className={`dashboard-state${error ? " error-state" : ""}`}
      role={error ? "alert" : "status"}
    >
      <span className="loading-orb" aria-hidden="true" />
      <h2>{title}</h2>
      {text !== undefined && <p>{text}</p>}
    </section>
  );
}

function modeLabel(mode: InsightResponse["mode"]): string {
  if (mode === "local-model") return "Local model + verified facts";
  if (mode === "refusal") return "Safety refusal";
  return "Verified template fallback";
}
