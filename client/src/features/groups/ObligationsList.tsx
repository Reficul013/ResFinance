import { useState } from "react";

import { formatUsd } from "../finance/money";
import {
  decideObligation,
  isGroupWritePending,
  settleObligation,
  type Dashboard,
  type GroupObligation,
  type GroupOverview,
} from "./groupActions";
import { PersonName } from "./MemberName";
import type { GroupAction } from "./useGroupAction";

export function ObligationsList({
  actorAddress,
  group,
  dashboard,
  obligations,
  action,
}: {
  actorAddress: string;
  group: GroupOverview;
  dashboard: Dashboard;
  obligations: readonly GroupObligation[];
  action: GroupAction;
}) {
  const [settlements, setSettlements] = useState<Record<string, string>>({});
  const yourCredits = group.credit_balances[actorAddress]?.minor_units ?? 0;
  const expenseNames = new Map(
    group.expenses.map((expense) => [expense.expense_id, expense.description]),
  );
  const disabled = isGroupWritePending(dashboard) || action.busy;
  return (
    <ul className="obligation-list">
      {obligations.map((obligation) => {
        const isDebtor = obligation.debtor_address === actorAddress;
        const maySettle =
          isDebtor && ["open", "partially_settled"].includes(obligation.status);
        return (
          <li key={obligation.obligation_id} className="obligation-card">
            <div className="obligation-summary">
              <span className={`status-pill ${obligation.status}`}>
                {obligation.status.replace("_", " ")}
              </span>
              <h3>
                {formatUsd(obligation.outstanding_amount.minor_units)}{" "}
                outstanding
              </h3>
              <p className="obligation-parties">
                <PersonName
                  address={obligation.debtor_address}
                  members={group.members}
                  actorAddress={actorAddress}
                />{" "}
                {isDebtor ? "owe" : "owes"}{" "}
                <PersonName
                  address={obligation.creditor_address}
                  members={group.members}
                  actorAddress={actorAddress}
                  capitalized={false}
                />
                {expenseNames.has(obligation.expense_id) &&
                  ` for ${expenseNames.get(obligation.expense_id)}`}
              </p>
              <p>
                Original {formatUsd(obligation.amount.minor_units)}
                {obligation.settled_amount.minor_units > 0 &&
                  ` · ${formatUsd(obligation.settled_amount.minor_units)} settled`}
                {obligation.due_on !== null && ` · Due ${obligation.due_on}`}
              </p>
            </div>
            {isDebtor && obligation.status === "pending" && (
              <div className="inline-actions">
                <button
                  className="primary-button"
                  type="button"
                  disabled={disabled}
                  onClick={() =>
                    void action.run((steps) =>
                      decideObligation(
                        dashboard,
                        group,
                        obligation.obligation_id,
                        "approve",
                        steps,
                      ),
                    )
                  }
                >
                  Approve in ResWallet
                </button>
                <button
                  className="secondary-button"
                  type="button"
                  disabled={disabled}
                  onClick={() =>
                    void action.run((steps) =>
                      decideObligation(
                        dashboard,
                        group,
                        obligation.obligation_id,
                        "reject",
                        steps,
                      ),
                    )
                  }
                >
                  Reject
                </button>
              </div>
            )}
            {maySettle && (
              <form
                className="inline-settlement"
                onSubmit={(event) => {
                  event.preventDefault();
                  const amount = settlements[obligation.obligation_id] ?? "";
                  void action.run((steps) =>
                    settleObligation(
                      dashboard,
                      group,
                      obligation.obligation_id,
                      amount,
                      steps,
                    ),
                  );
                }}
              >
                <label className="form-field">
                  <span>Partial or full amount</span>
                  <input
                    value={settlements[obligation.obligation_id] ?? ""}
                    onChange={(event) =>
                      setSettlements((current) => ({
                        ...current,
                        [obligation.obligation_id]: event.target.value,
                      }))
                    }
                    placeholder={(
                      obligation.outstanding_amount.minor_units / 100
                    ).toFixed(2)}
                    inputMode="decimal"
                    required
                  />
                </label>
                <button className="primary-button" disabled={disabled}>
                  Settle with credits
                </button>
                {yourCredits < obligation.outstanding_amount.minor_units && (
                  <p className="form-hint settle-hint">
                    You have {formatUsd(yourCredits)} in credits. Fund{" "}
                    {formatUsd(
                      obligation.outstanding_amount.minor_units - yourCredits,
                    )}{" "}
                    more under Fund internal credits to settle this in full.
                  </p>
                )}
              </form>
            )}
          </li>
        );
      })}
    </ul>
  );
}
