import { formatUsd } from "../finance/money";
import type { GroupExpense, GroupOverview } from "./groupActions";
import { PersonName } from "./MemberName";

export function ExpenseList({
  actorAddress,
  members,
  expenses,
}: {
  actorAddress: string;
  members: GroupOverview["members"];
  expenses: readonly GroupExpense[];
}) {
  return (
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
                  members={members}
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
                  members={members}
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
