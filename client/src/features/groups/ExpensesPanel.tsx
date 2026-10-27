import { useEffect, useId, useRef, useState } from "react";

import { formatUsd } from "../finance/money";
import type { GroupExpense, GroupOverview } from "./groupActions";
import { PersonName } from "./MemberName";

export const VISIBLE_SHARES = 8;

export function previewShares<T>(shares: readonly T[]): {
  visible: T[];
  hiddenCount: number;
} {
  return {
    visible: shares.slice(0, VISIBLE_SHARES),
    hiddenCount: Math.max(0, shares.length - VISIBLE_SHARES),
  };
}

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
        <ExpenseCard
          key={expense.expense_id}
          actorAddress={actorAddress}
          members={members}
          expense={expense}
        />
      ))}
    </ul>
  );
}

function ExpenseCard({
  actorAddress,
  members,
  expense,
}: {
  actorAddress: string;
  members: GroupOverview["members"];
  expense: GroupExpense;
}) {
  const entries = Object.entries(expense.shares);
  const { visible, hiddenCount } = previewShares(entries);
  const hidden = entries.slice(visible.length);
  const [open, setOpen] = useState(false);
  const overflowRef = useRef<HTMLDivElement>(null);
  const popoverId = useId();

  useEffect(() => {
    if (!open) return;
    function closeOnOutsidePointer(event: PointerEvent) {
      if (!overflowRef.current?.contains(event.target as Node)) setOpen(false);
    }
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("pointerdown", closeOnOutsidePointer);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsidePointer);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  return (
    <li className="expense-card">
      <div className="expense-heading">
        <div>
          <h3 title={expense.description}>{expense.description}</h3>
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
      <div className="expense-share-row">
        <ul
          className="expense-shares"
          aria-label={`Split for ${expense.description}`}
        >
          {visible.map(([address, share]) => (
            <ShareChip
              key={address}
              address={address}
              amount={formatUsd(share.minor_units)}
              ownShare={address === expense.payer_address}
              actorAddress={actorAddress}
              members={members}
            />
          ))}
        </ul>
        {hiddenCount > 0 && (
          <div className="share-overflow" ref={overflowRef}>
            <button
              type="button"
              className="share-more"
              aria-expanded={open}
              aria-controls={popoverId}
              onClick={() => setOpen((current) => !current)}
            >
              {hiddenCount} more
            </button>
            {open && (
              <div
                id={popoverId}
                className="share-popover"
                role="dialog"
                aria-label={`Other people in ${expense.description}`}
              >
                <ul>
                  {hidden.map(([address, share]) => (
                    <ShareChip
                      key={address}
                      address={address}
                      amount={formatUsd(share.minor_units)}
                      ownShare={address === expense.payer_address}
                      actorAddress={actorAddress}
                      members={members}
                    />
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>
    </li>
  );
}

function ShareChip({
  address,
  amount,
  ownShare,
  actorAddress,
  members,
}: {
  address: string;
  amount: string;
  ownShare: boolean;
  actorAddress: string;
  members: GroupOverview["members"];
}) {
  return (
    <li>
      <PersonName
        address={address}
        members={members}
        actorAddress={actorAddress}
      />
      <span>{amount}</span>
      {ownShare && <span className="member-tag">Own share</span>}
    </li>
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
