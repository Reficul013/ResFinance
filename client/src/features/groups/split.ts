import { formatUsd, usdToMinorUnits } from "../finance/money";

export interface SplitRow {
  address: string;
  name: string;
  included: boolean;
  amount: string;
}

export type SplitMode = "equal" | "exact";

export function equalShares(
  totalMinorUnits: number,
  addresses: readonly string[],
  payerAddress: string,
): Record<string, number> {
  if (addresses.length === 0) return {};
  const payer = payerAddress.toLowerCase();
  const base = Math.floor(totalMinorUnits / addresses.length);
  let remainder = totalMinorUnits - base * addresses.length;
  const shares: Record<string, number> = {};
  for (const address of [
    ...addresses.filter((item) => item.toLowerCase() === payer),
    ...addresses.filter((item) => item.toLowerCase() !== payer),
  ]) {
    shares[address] = base + (remainder > 0 ? 1 : 0);
    if (remainder > 0) remainder -= 1;
  }
  return shares;
}

export function applyEqualSplit(
  total: string,
  rows: readonly SplitRow[],
  payerAddress: string,
): SplitRow[] {
  const totalMinorUnits = optionalMinorUnits(total);
  if (totalMinorUnits === null)
    return rows.map((row) => ({ ...row, amount: "" }));
  const shares = equalShares(
    totalMinorUnits,
    rows.filter((row) => row.included).map((row) => row.address),
    payerAddress,
  );
  return rows.map((row) => ({
    ...row,
    amount: row.included ? minorUnitsToAmount(shares[row.address]!) : "",
  }));
}

export function minorUnitsToAmount(minorUnits: number): string {
  return `${Math.floor(minorUnits / 100)}.${String(minorUnits % 100).padStart(2, "0")}`;
}

export interface SplitProgress {
  totalMinorUnits: number | null;
  assignedMinorUnits: number;
  remainingMinorUnits: number | null;
}

export function splitProgress(
  total: string,
  rows: readonly SplitRow[],
): SplitProgress {
  const totalMinorUnits = optionalMinorUnits(total);
  const assignedMinorUnits = rows
    .filter((row) => row.included)
    .reduce((sum, row) => sum + (optionalMinorUnits(row.amount) ?? 0), 0);
  return {
    totalMinorUnits,
    assignedMinorUnits,
    remainingMinorUnits:
      totalMinorUnits === null ? null : totalMinorUnits - assignedMinorUnits,
  };
}

export function buildShares(
  total: string,
  rows: readonly SplitRow[],
  payerAddress: string,
): { amountMinorUnits: number; shares: Record<string, number> } {
  const amountMinorUnits = labelledMinorUnits("Total amount", total);
  const included = rows.filter((row) => row.included);
  if (included.length === 0)
    throw new Error("Choose at least one member to split with.");
  const payer = payerAddress.toLowerCase();
  if (included.every((row) => row.address.toLowerCase() === payer))
    throw new Error(
      "Include at least one other member. Your own share does not create a debt.",
    );

  const shares: Record<string, number> = {};
  for (const row of included) {
    shares[row.address.toLowerCase()] = labelledMinorUnits(
      `${row.name}'s share`,
      row.amount,
    );
  }
  const assigned = Object.values(shares).reduce((sum, item) => sum + item, 0);
  const difference = amountMinorUnits - assigned;
  if (difference > 0)
    throw new Error(
      `Shares add up to ${formatUsd(assigned)}, but the total is ${formatUsd(amountMinorUnits)}. Assign the remaining ${formatUsd(difference)}.`,
    );
  if (difference < 0)
    throw new Error(
      `Shares add up to ${formatUsd(assigned)}, which is ${formatUsd(-difference)} more than the total of ${formatUsd(amountMinorUnits)}.`,
    );
  return { amountMinorUnits, shares };
}

function optionalMinorUnits(value: string): number | null {
  if (value.trim() === "") return null;
  try {
    return usdToMinorUnits(value);
  } catch {
    return null;
  }
}

function labelledMinorUnits(label: string, value: string): number {
  try {
    return usdToMinorUnits(value);
  } catch (error) {
    throw new Error(
      `${label}: ${error instanceof Error ? error.message : "invalid amount"}`,
      { cause: error },
    );
  }
}
