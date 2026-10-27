export const ACTIVITY_PAGE_SIZE = 6;

export type ObligationFilter = "action" | "open" | "settled" | "all";
export type ExpenseFilter = "all" | "mine";

export interface ObligationLike {
  creditor_address: string;
  debtor_address: string;
  status:
    | "pending"
    | "open"
    | "partially_settled"
    | "settled"
    | "rejected"
    | "cancelled";
  outstanding_amount: { minor_units: number };
}

const UNRESOLVED = new Set(["pending", "open", "partially_settled"]);
const CONFIRMED_OUTSTANDING = new Set(["open", "partially_settled"]);

export function needsAction(
  obligation: ObligationLike,
  actorAddress: string,
): boolean {
  return (
    sameAddress(obligation.debtor_address, actorAddress) &&
    UNRESOLVED.has(obligation.status)
  );
}

export function filterObligations<T extends ObligationLike>(
  obligations: readonly T[],
  filter: ObligationFilter,
  actorAddress: string,
): T[] {
  switch (filter) {
    case "action":
      return obligations.filter((item) => needsAction(item, actorAddress));
    case "open":
      return obligations.filter((item) => UNRESOLVED.has(item.status));
    case "settled":
      return obligations.filter((item) => item.status === "settled");
    case "all":
      return [...obligations];
  }
}

export function obligationCounts(
  obligations: readonly ObligationLike[],
  actorAddress: string,
): Record<ObligationFilter, number> {
  return {
    action: filterObligations(obligations, "action", actorAddress).length,
    open: filterObligations(obligations, "open", actorAddress).length,
    settled: filterObligations(obligations, "settled", actorAddress).length,
    all: obligations.length,
  };
}

export function filterExpenses<T extends { payer_address: string }>(
  expenses: readonly T[],
  filter: ExpenseFilter,
  actorAddress: string,
): T[] {
  return filter === "mine"
    ? expenses.filter((item) => sameAddress(item.payer_address, actorAddress))
    : [...expenses];
}

export function pageItems<T>(
  items: readonly T[],
  visible: number,
): { items: T[]; remaining: number } {
  const shown = items.slice(0, Math.max(0, visible));
  return { items: shown, remaining: items.length - shown.length };
}

export function groupTotals(
  obligations: readonly ObligationLike[],
  actorAddress: string,
): { oweMinorUnits: number; owedMinorUnits: number } {
  let oweMinorUnits = 0;
  let owedMinorUnits = 0;
  for (const item of obligations) {
    if (!CONFIRMED_OUTSTANDING.has(item.status)) continue;
    if (sameAddress(item.debtor_address, actorAddress))
      oweMinorUnits += item.outstanding_amount.minor_units;
    else if (sameAddress(item.creditor_address, actorAddress))
      owedMinorUnits += item.outstanding_amount.minor_units;
  }
  return { oweMinorUnits, owedMinorUnits };
}

function sameAddress(left: string, right: string): boolean {
  return left.toLowerCase() === right.toLowerCase();
}
