import type { GroupOverview } from "../../lib/api/client";
import { formatUsd } from "../finance/money";
import { PersonName } from "./MemberName";

export function ExpensesPanel({
  actorAddress,
  group,
}: {
  actorAddress: string;
  group: GroupOverview;
}) {
  const expenses = newestFirst(group.expenses);
  return (
    <section className="panel expenses-panel" aria-labelledby="expenses-title">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">History</p>
          <h2 id="expenses-title">Expenses</h2>
        </div>
        <span className="provenance-chip">{expenses.length} total</span>
      </div>
      {expenses.length === 0 ? (
        <p className="empty-copy">
          No expenses yet. Add one above to split it with the group.
        </p>
      ) : (
        <ul className="expense-list">
          {expenses.map((expense) => (
            <li key={expense.expense_id} className="expense-card">
              <div className="expense-heading">
                <div>
                  <h3>{expense.description}</h3>
                  <p>
                    {formatExpenseDate(expense.occurred_on)} · Paid by{" "}
                    <PersonName
                      address={expense.payer_address}
                      members={group.members}
                      actorAddress={actorAddress}
                      capitalized={false}
                    />
                  </p>
                </div>
                <strong className="expense-total">
                  {formatUsd(expense.amount.minor_units)}
                </strong>
              </div>
              <ul
                className="expense-shares"
                aria-label={`Split for ${expense.description}`}
              >
                {Object.entries(expense.shares).map(([address, share]) => (
                  <li key={address}>
                    <PersonName
                      address={address}
                      members={group.members}
                      actorAddress={actorAddress}
                    />
                    <span>{formatUsd(share.minor_units)}</span>
                    {address === expense.payer_address && (
                      <span className="member-tag">Own share</span>
                    )}
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function newestFirst<T extends { occurred_on: string }>(
  expenses: readonly T[],
): T[] {
  return [...expenses]
    .reverse()
    .sort((left, right) => right.occurred_on.localeCompare(left.occurred_on));
}

export function formatExpenseDate(value: string): string {
  return new Date(`${value}T00:00:00`).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}
