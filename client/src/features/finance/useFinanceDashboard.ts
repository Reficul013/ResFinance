import {
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import {
  createFinanceRecurringEntry,
  deactivateFinanceRecurringEntry,
  getFinanceOverview,
  recordFinanceTransaction,
  setFinanceBudget,
  voidFinanceTransaction,
  type BudgetCommand,
  type DeactivateRecurringCommand,
  type RecurringEntryCommand,
  type TransactionCommand,
  type VoidTransactionCommand,
} from "../../lib/api/client";

interface Command<T> {
  body: T;
  idempotencyKey: string;
}

interface RecordCommand<T> extends Command<T> {
  recordId: string;
}

export function useFinanceDashboard(accessToken: string, month: string) {
  const queryClient = useQueryClient();
  const queryKey = ["finance-overview", accessToken, month] as const;
  const overview = useQuery({
    queryKey,
    queryFn: ({ signal }) => getFinanceOverview(accessToken, month, signal),
  });
  const refresh = async () => {
    await queryClient.invalidateQueries({
      queryKey: ["finance-overview", accessToken],
    });
  };
  const historyMonths = financeTrendMonths(month);
  const history = useQueries({
    queries: historyMonths.map((historyMonth) => ({
      queryKey: ["finance-overview", accessToken, historyMonth] as const,
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        getFinanceOverview(accessToken, historyMonth, signal),
    })),
  });
  const transaction = useMutation({
    mutationFn: ({ body, idempotencyKey }: Command<TransactionCommand>) =>
      recordFinanceTransaction(accessToken, idempotencyKey, body),
    onSuccess: refresh,
  });
  const voidTransaction = useMutation({
    mutationFn: ({
      recordId,
      body,
      idempotencyKey,
    }: RecordCommand<VoidTransactionCommand>) =>
      voidFinanceTransaction(accessToken, recordId, idempotencyKey, body),
    onSuccess: refresh,
  });
  const budget = useMutation({
    mutationFn: ({ body, idempotencyKey }: Command<BudgetCommand>) =>
      setFinanceBudget(accessToken, idempotencyKey, body),
    onSuccess: refresh,
  });
  const recurring = useMutation({
    mutationFn: ({ body, idempotencyKey }: Command<RecurringEntryCommand>) =>
      createFinanceRecurringEntry(accessToken, idempotencyKey, body),
    onSuccess: refresh,
  });
  const deactivateRecurring = useMutation({
    mutationFn: ({
      recordId,
      body,
      idempotencyKey,
    }: RecordCommand<DeactivateRecurringCommand>) =>
      deactivateFinanceRecurringEntry(
        accessToken,
        recordId,
        idempotencyKey,
        body,
      ),
    onSuccess: refresh,
  });
  return {
    overview,
    historyMonths,
    history,
    transaction,
    voidTransaction,
    budget,
    recurring,
    deactivateRecurring,
  };
}

function financeTrendMonths(month: string): string[] {
  const selected = new Date(`${month}-01T00:00:00Z`);
  return Array.from({ length: 9 }, (_, index) => {
    const date = new Date(selected);
    date.setUTCMonth(selected.getUTCMonth() + index - 5);
    return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}`;
  });
}
