import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createFinanceCategory,
  createFinanceRecurringEntry,
  getFinanceOverview,
  recordFinanceTransaction,
  setFinanceBudget,
  type BudgetCommand,
  type CategoryCommand,
  type RecurringEntryCommand,
  type TransactionCommand,
} from "../../lib/api/client";

interface Command<T> {
  body: T;
  idempotencyKey: string;
}

export function useFinanceDashboard(accessToken: string, month: string) {
  const queryClient = useQueryClient();
  const queryKey = ["finance-overview", accessToken, month] as const;
  const overview = useQuery({
    queryKey,
    queryFn: ({ signal }) => getFinanceOverview(accessToken, month, signal),
  });
  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey });
  };
  const category = useMutation({
    mutationFn: ({ body, idempotencyKey }: Command<CategoryCommand>) =>
      createFinanceCategory(accessToken, idempotencyKey, body),
    onSuccess: refresh,
  });
  const transaction = useMutation({
    mutationFn: ({ body, idempotencyKey }: Command<TransactionCommand>) =>
      recordFinanceTransaction(accessToken, idempotencyKey, body),
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
  return { overview, category, transaction, budget, recurring };
}
