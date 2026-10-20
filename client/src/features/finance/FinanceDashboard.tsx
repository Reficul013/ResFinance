import { useEffect, useRef, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { FinanceOverview } from "../../lib/api/client";
import { FinanceEntryForms } from "./FinanceEntryForms";
import { FinanceAnalytics } from "./FinanceAnalytics";
import { currentMonth, formatUsd } from "./money";
import { useFinanceDashboard } from "./useFinanceDashboard";
import { SmartSavingsInsights } from "../insights/InsightsDashboard";

interface FinanceDashboardProps {
  accessToken: string;
}

type RecordAction =
  | {
      kind: "void-transaction";
      recordId: string;
      label: string;
    }
  | {
      kind: "deactivate-recurring";
      recordId: string;
      label: string;
    };

export function FinanceDashboard({ accessToken }: FinanceDashboardProps) {
  const [month, setMonth] = useState(currentMonth());
  const [recordAction, setRecordAction] = useState<RecordAction | null>(null);
  const dashboard = useFinanceDashboard(accessToken, month);

  if (dashboard.overview.isPending) {
    return (
      <section className="dashboard-state" aria-live="polite" aria-busy="true">
        <span className="loading-orb" aria-hidden="true" />
        <h2>Rebuilding your finance view…</h2>
        <p>Reading and reducing encrypted events from ResilientDB.</p>
      </section>
    );
  }

  if (dashboard.overview.isError) {
    return (
      <section className="dashboard-state error-state" role="alert">
        <p className="section-kicker">Finance unavailable</p>
        <h2>We couldn’t load your finance data.</h2>
        <p>{dashboard.overview.error.message}</p>
        <button
          className="primary-button"
          type="button"
          onClick={() => void dashboard.overview.refetch()}
        >
          Try again
        </button>
      </section>
    );
  }

  const overview = dashboard.overview.data;
  const openRecordAction = (action: RecordAction) => {
    dashboard.voidTransaction.reset();
    dashboard.deactivateRecurring.reset();
    setRecordAction(action);
  };
  const confirmRecordAction = async (reason: string) => {
    if (recordAction === null) return;
    const idempotencyKey = `${recordAction.kind}-${crypto.randomUUID()}`;
    try {
      if (recordAction.kind === "void-transaction") {
        await dashboard.voidTransaction.mutateAsync({
          recordId: recordAction.recordId,
          idempotencyKey,
          body: {
            reason,
            expected_version: overview.provenance.projection_version,
          },
        });
      } else {
        await dashboard.deactivateRecurring.mutateAsync({
          recordId: recordAction.recordId,
          idempotencyKey,
          body: { expected_version: overview.provenance.projection_version },
        });
      }
      setRecordAction(null);
    } catch {
      // The mutation exposes its API error inside the confirmation dialog.
    }
  };
  const actionPending =
    dashboard.voidTransaction.isPending ||
    dashboard.deactivateRecurring.isPending;
  const actionError =
    dashboard.voidTransaction.error ?? dashboard.deactivateRecurring.error;
  return (
    <div className="finance-dashboard">
      <section className="dashboard-header" aria-labelledby="finance-title">
        <div>
          <p className="eyebrow">Personal Finance</p>
          <h1 id="finance-title">Your money, in one view.</h1>
          <p className="lede">
            Track cash flow, monthly limits, recurring commitments, and the
            exact savings amount that will feed future portfolio analysis.
          </p>
        </div>
        <label className="month-control">
          <span>Reporting month</span>
          <input
            type="month"
            value={month}
            onChange={(event) => setMonth(event.target.value)}
          />
        </label>
      </section>

      <SummaryCards overview={overview} />
      <FinanceEntryForms
        dashboard={dashboard}
        overview={overview}
        month={month}
      />
      <div className="dashboard-columns">
        <CashFlowChart overview={overview} />
        <BudgetPanel overview={overview} />
      </div>
      <FinanceAnalytics
        overview={overview}
        historyMonths={dashboard.historyMonths}
        history={dashboard.history.map((item) => item.data)}
      />
      <div className="dashboard-columns records-columns">
        <TransactionPanel overview={overview} onAction={openRecordAction} />
        <CommitmentsPanel overview={overview} onAction={openRecordAction} />
      </div>
      <SmartSavingsInsights
        accessToken={accessToken}
        month={month}
        financeOverview={overview}
      />
      {recordAction === null ? null : (
        <RecordActionDialog
          action={recordAction}
          error={actionError}
          pending={actionPending}
          onCancel={() => setRecordAction(null)}
          onConfirm={confirmRecordAction}
        />
      )}
    </div>
  );
}

export function SummaryCards({ overview }: { overview: FinanceOverview }) {
  const summary = overview.summary;
  const cards = [
    ["Net balance", summary.balance.minor_units, "All recorded cash flow"],
    ["Income", summary.income.minor_units, summary.month],
    ["Expenses", summary.expense.minor_units, summary.month],
    [
      "Available savings",
      summary.savings.available.minor_units,
      "After recurring entries and obligations",
    ],
  ] as const;
  return (
    <section className="summary-grid" aria-label="Finance summary">
      {cards.map(([label, amount, note]) => (
        <article className="metric-card" key={label}>
          <p>{label}</p>
          <strong>{formatUsd(amount)}</strong>
          <small>{note}</small>
        </article>
      ))}
    </section>
  );
}

function CashFlowChart({ overview }: { overview: FinanceOverview }) {
  const { summary } = overview;
  const data = [
    { label: "Income", amount: summary.income.minor_units },
    { label: "Expenses", amount: summary.expense.minor_units },
    {
      label: "Estimated savings",
      amount: summary.savings.projected.minor_units,
    },
  ];
  return (
    <section className="panel chart-panel" aria-labelledby="cash-flow-title">
      <div className="section-heading compact">
        <div>
          <p className="section-kicker">Monthly shape</p>
          <h2 id="cash-flow-title">Cash flow</h2>
        </div>
      </div>
      <div
        className="chart-wrap"
        role="img"
        aria-label={`Income ${formatUsd(summary.income.minor_units)}, expenses ${formatUsd(summary.expense.minor_units)}, estimated savings ${formatUsd(summary.savings.projected.minor_units)}`}
      >
        <ResponsiveContainer width="100%" height={240}>
          <BarChart
            data={data}
            margin={{ top: 18, right: 4, left: 4, bottom: 0 }}
          >
            <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
            <XAxis
              dataKey="label"
              tick={{ fill: "var(--page-muted)", fontSize: 12 }}
            />
            <YAxis
              tick={{ fill: "var(--page-muted)", fontSize: 12 }}
              tickFormatter={(value: number) => formatUsd(value)}
            />
            <Tooltip formatter={(value) => formatUsd(Number(value))} />
            <Bar
              dataKey="amount"
              fill="var(--page-accent)"
              radius={[8, 8, 2, 2]}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="panel-note">
        Estimated savings includes unmatched monthly recurring entries and open
        obligations due this month.
      </p>
    </section>
  );
}

function BudgetPanel({ overview }: { overview: FinanceOverview }) {
  const statuses = overview.summary.budget_statuses;
  return (
    <section className="panel" aria-labelledby="budget-title">
      <div className="section-heading compact">
        <div>
          <p className="section-kicker">Guardrails</p>
          <h2 id="budget-title">Budgets</h2>
        </div>
      </div>
      {statuses.length === 0 ? (
        <EmptyState text="No budgets for this month yet." />
      ) : (
        <ul className="budget-list">
          {statuses.map((budget) => (
            <li key={budget.budget_id} data-status={budget.status}>
              <div className="budget-row">
                <strong>{budget.category_name}</strong>
                <span>
                  {formatUsd(budget.spent.minor_units)} /{" "}
                  {formatUsd(budget.limit.minor_units)}
                </span>
              </div>
              <progress
                max={10_000}
                value={Math.min(budget.utilization_basis_points, 10_000)}
                aria-label={`${budget.category_name} budget utilization`}
              />
              <small>
                {budget.status === "over_budget"
                  ? "Over budget"
                  : budget.status === "near_limit"
                    ? "Near the limit"
                    : `${formatUsd(budget.remaining.minor_units)} remaining`}
              </small>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function TransactionPanel({
  overview,
  onAction,
}: {
  overview: FinanceOverview;
  onAction: (action: RecordAction) => void;
}) {
  const active = overview.transactions.filter((item) => !item.voided);
  const categories = new Map(
    overview.categories.map((item) => [item.category_id, item.name]),
  );
  return (
    <section className="panel" aria-labelledby="transactions-title">
      <div className="section-heading compact">
        <div>
          <p className="section-kicker">Event ledger</p>
          <h2 id="transactions-title">Recent Transactions</h2>
        </div>
      </div>
      {active.length === 0 ? (
        <EmptyState text="No transactions yet. Add income or an expense above." />
      ) : (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th scope="col">Date</th>
                <th scope="col">Description</th>
                <th scope="col">Category</th>
                <th scope="col">Amount</th>
                <th scope="col" className="record-actions-heading">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {active.slice(0, 8).map((entry) => (
                <tr key={entry.transaction_id}>
                  <td>{entry.occurred_on}</td>
                  <td>{entry.description}</td>
                  <td>{categories.get(entry.category_id) ?? "Unknown"}</td>
                  <td className={entry.direction}>
                    {entry.direction === "expense" ? "−" : "+"}
                    {formatUsd(entry.amount.minor_units)}
                  </td>
                  <td className="record-actions-cell">
                    <RecordActionMenu
                      label={entry.description}
                      actionLabel="Void Transaction"
                      onAction={() =>
                        onAction({
                          kind: "void-transaction",
                          recordId: entry.transaction_id,
                          label: entry.description,
                        })
                      }
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function CommitmentsPanel({
  overview,
  onAction,
}: {
  overview: FinanceOverview;
  onAction: (action: RecordAction) => void;
}) {
  const recurring = overview.recurring_entries.filter((item) => item.active);
  const openObligations = overview.obligations.filter((item) => !item.settled);
  return (
    <section className="panel" aria-labelledby="commitments-title">
      <div className="section-heading compact">
        <div>
          <p className="section-kicker">Looking ahead</p>
          <h2 id="commitments-title">Commitments</h2>
        </div>
      </div>
      {recurring.length === 0 && openObligations.length === 0 ? (
        <EmptyState text="No recurring entries or group obligations yet." />
      ) : (
        <ul className="commitment-list">
          {recurring.map((item) => (
            <li key={item.recurring_entry_id}>
              <span
                className={`direction-icon ${item.direction}`}
                aria-hidden="true"
              >
                {item.direction === "income" ? "+" : "−"}
              </span>
              <div>
                <strong>{item.description}</strong>
                <small>Monthly from {item.starts_on}</small>
              </div>
              <span>{formatUsd(item.amount.minor_units)}</span>
              <RecordActionMenu
                label={item.description}
                actionLabel="Deactivate Recurring Item"
                onAction={() =>
                  onAction({
                    kind: "deactivate-recurring",
                    recordId: item.recurring_entry_id,
                    label: item.description,
                  })
                }
              />
            </li>
          ))}
          {openObligations.map((item) => (
            <li key={item.obligation_id}>
              <span
                className={`direction-icon ${item.direction}`}
                aria-hidden="true"
              >
                {item.direction === "receivable" ? "+" : "−"}
              </span>
              <div>
                <strong>
                  {item.direction === "receivable" ? "Receivable" : "Payable"}
                </strong>
                <small>
                  {item.due_on === null ? "No due date" : `Due ${item.due_on}`}
                </small>
              </div>
              <span>{formatUsd(item.amount.minor_units)}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function RecordActionMenu({
  label,
  actionLabel,
  onAction,
}: {
  label: string;
  actionLabel: string;
  onAction: () => void;
}) {
  return (
    <details className="record-action-menu">
      <summary
        role="button"
        aria-label={`Actions for ${label}`}
        title={`Actions for ${label}`}
      >
        <span aria-hidden="true">•••</span>
      </summary>
      <div role="menu">
        <button
          type="button"
          role="menuitem"
          onClick={(event) => {
            event.currentTarget.closest("details")?.removeAttribute("open");
            onAction();
          }}
        >
          {actionLabel}
        </button>
      </div>
    </details>
  );
}

function RecordActionDialog({
  action,
  error,
  pending,
  onCancel,
  onConfirm,
}: {
  action: RecordAction;
  error: Error | null;
  pending: boolean;
  onCancel: () => void;
  onConfirm: (reason: string) => Promise<void>;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [reason, setReason] = useState("");
  const voiding = action.kind === "void-transaction";

  useEffect(() => {
    const element = dialog.current;
    if (element !== null && !element.open) element.showModal();
    return () => {
      if (element?.open) element.close();
    };
  }, []);

  return (
    <dialog
      ref={dialog}
      className="record-action-dialog"
      aria-labelledby="record-action-title"
      onCancel={(event) => {
        if (pending) {
          event.preventDefault();
          return;
        }
        onCancel();
      }}
    >
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void onConfirm(reason.trim());
        }}
      >
        <p className="section-kicker">Confirm ledger change</p>
        <h2 id="record-action-title">
          {voiding
            ? "Void this transaction?"
            : "Deactivate this recurring item?"}
        </h2>
        <p>
          {voiding
            ? `“${action.label}” will stop affecting your active financial calculations.`
            : `“${action.label}” will stop affecting projected savings calculations.`}
        </p>
        <p className="audit-note">
          The original record remains in the append-only audit trail. This
          action adds a new event and does not erase history.
        </p>
        {voiding ? (
          <label className="form-field">
            <span>Reason for voiding</span>
            <textarea
              autoFocus
              required
              maxLength={160}
              rows={3}
              value={reason}
              placeholder="For example: Duplicate transaction"
              onChange={(event) => setReason(event.target.value)}
            />
          </label>
        ) : null}
        {error === null ? null : (
          <p className="form-error" role="alert">
            {error.message}
          </p>
        )}
        <div className="dialog-actions">
          <button
            className="secondary-button"
            type="button"
            disabled={pending}
            onClick={onCancel}
          >
            Cancel
          </button>
          <button
            className="destructive-button"
            type="submit"
            disabled={pending || (voiding && reason.trim().length === 0)}
          >
            {pending
              ? "Saving…"
              : voiding
                ? "Void Transaction"
                : "Deactivate Recurring Item"}
          </button>
        </div>
      </form>
    </dialog>
  );
}

function EmptyState({ text }: { text: string }) {
  return <p className="empty-state">{text}</p>;
}
