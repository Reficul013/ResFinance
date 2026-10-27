import { useId } from "react";

import { formatUsd } from "../finance/money";
import { MemberName } from "./MemberName";
import type { GroupMemberLike } from "./members";
import type { SplitMode, SplitProgress, SplitRow } from "./split";

export function SplitEditor({
  mode,
  rows,
  members,
  payerAddress,
  payerName,
  progress,
  onModeChange,
  onToggle,
  onAmountChange,
}: {
  mode: SplitMode;
  rows: readonly SplitRow[];
  members: readonly GroupMemberLike[];
  payerAddress: string;
  payerName: string;
  progress: SplitProgress;
  onModeChange(mode: SplitMode): void;
  onToggle(address: string, included: boolean): void;
  onAmountChange(address: string, amount: string): void;
}) {
  const modeName = useId();
  const includedCount = rows.filter((row) => row.included).length;
  const status = progressStatus(progress, mode, includedCount);
  return (
    <fieldset className="split-editor wide-field">
      <legend>Split between</legend>
      <div className="split-mode" role="radiogroup" aria-label="How to split">
        <label>
          <input
            type="radio"
            name={modeName}
            checked={mode === "equal"}
            onChange={() => onModeChange("equal")}
          />
          Split equally
        </label>
        <label>
          <input
            type="radio"
            name={modeName}
            checked={mode === "exact"}
            onChange={() => onModeChange("exact")}
          />
          Exact amounts
        </label>
      </div>
      <p className="form-note">
        Paid by you ({payerName}). Tick everyone who shares this expense.{" "}
        {mode === "equal"
          ? "The total is divided equally between them."
          : "Enter each person's amount."}{" "}
        Your own share does not create a debt.
      </p>
      <ul>
        {rows.map((row) => (
          <li
            key={row.address}
            className={row.included ? "included" : "excluded"}
          >
            <input
              type="checkbox"
              aria-label={`Include ${row.name}`}
              checked={row.included}
              onChange={(event) => onToggle(row.address, event.target.checked)}
            />
            <span className="split-member">
              <MemberName address={row.address} members={members} />
              {row.address === payerAddress && (
                <span className="member-tag">You</span>
              )}
            </span>
            {mode === "equal" ? (
              <span className="split-amount">
                {!row.included
                  ? "Not included"
                  : row.amount === ""
                    ? "—"
                    : formatUsd(Number(row.amount.replace(".", "")))}
              </span>
            ) : (
              <input
                aria-label={`${row.name}'s share`}
                value={row.included ? row.amount : ""}
                onChange={(event) =>
                  onAmountChange(row.address, event.target.value)
                }
                inputMode="decimal"
                placeholder={row.included ? "0.00" : "Not included"}
                disabled={!row.included}
              />
            )}
          </li>
        ))}
      </ul>
      <p className={`split-progress ${status.kind}`} aria-live="polite">
        {status.text}
      </p>
    </fieldset>
  );
}

function progressStatus(
  progress: SplitProgress,
  mode: SplitMode,
  includedCount: number,
): {
  kind: "pending" | "balanced" | "over";
  text: string;
} {
  const assigned = formatUsd(progress.assignedMinorUnits);
  if (
    progress.totalMinorUnits === null ||
    progress.remainingMinorUnits === null
  )
    return {
      kind: "pending",
      text:
        mode === "equal"
          ? "Enter the total to split it equally."
          : `Enter the total to see what is left to assign. Assigned so far: ${assigned}.`,
    };
  const total = formatUsd(progress.totalMinorUnits);
  if (mode === "equal" && includedCount === 0)
    return { kind: "pending", text: "Tick at least one member to split with." };
  if (progress.remainingMinorUnits === 0)
    return {
      kind: "balanced",
      text:
        mode === "equal"
          ? `All ${total} assigned, split equally between ${includedCount} ${includedCount === 1 ? "person" : "people"}.`
          : `All ${total} assigned.`,
    };
  if (progress.remainingMinorUnits > 0)
    return {
      kind: "pending",
      text: `${assigned} of ${total} assigned · ${formatUsd(progress.remainingMinorUnits)} left`,
    };
  return {
    kind: "over",
    text: `${assigned} of ${total} assigned · ${formatUsd(-progress.remainingMinorUnits)} over`,
  };
}
