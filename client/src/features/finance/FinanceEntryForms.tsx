import { zodResolver } from "@hookform/resolvers/zod";
import { useForm, type UseFormRegisterReturn } from "react-hook-form";
import { z } from "zod";

import type { FinanceOverview } from "../../lib/api/client";
import { currentDate, usdToMinorUnits } from "./money";
import type { useFinanceDashboard } from "./useFinanceDashboard";

type Dashboard = ReturnType<typeof useFinanceDashboard>;

interface FinanceEntryFormsProps {
  dashboard: Dashboard;
  overview: FinanceOverview;
  month: string;
}

const categorySchema = z.object({
  name: z.string().trim().min(1, "Enter a category name.").max(80),
  direction: z.enum(["income", "expense"]),
});

const transactionSchema = z.object({
  direction: z.enum(["income", "expense"]),
  category_id: z.string().min(1, "Choose a category."),
  amount: z.string().refine(validAmount, "Enter a positive USD amount."),
  occurred_on: z.iso.date(),
  description: z.string().trim().min(1, "Enter a description.").max(160),
});

const budgetSchema = z.object({
  category_id: z.string().min(1, "Choose an expense category."),
  amount: z.string().refine(validAmount, "Enter a positive USD amount."),
});

const recurringSchema = transactionSchema.pick({
  direction: true,
  category_id: true,
  amount: true,
  description: true,
});

type CategoryValues = z.infer<typeof categorySchema>;
type TransactionValues = z.infer<typeof transactionSchema>;
type BudgetValues = z.infer<typeof budgetSchema>;
type RecurringValues = z.infer<typeof recurringSchema>;

export function FinanceEntryForms({
  dashboard,
  overview,
  month,
}: FinanceEntryFormsProps) {
  const category = useForm<CategoryValues>({
    resolver: zodResolver(categorySchema),
    defaultValues: { name: "", direction: "expense" },
  });
  const transaction = useForm<TransactionValues>({
    resolver: zodResolver(transactionSchema),
    defaultValues: {
      direction: "expense",
      category_id: "",
      amount: "",
      occurred_on: currentDate(),
      description: "",
    },
  });
  const budget = useForm<BudgetValues>({
    resolver: zodResolver(budgetSchema),
    defaultValues: { category_id: "", amount: "" },
  });
  const recurring = useForm<RecurringValues>({
    resolver: zodResolver(recurringSchema),
    defaultValues: {
      direction: "expense",
      category_id: "",
      amount: "",
      description: "",
    },
  });
  const transactionDirection = transaction.watch("direction");
  const recurringDirection = recurring.watch("direction");
  const expenseCategories = overview.categories.filter(
    (item) => item.active && item.direction === "expense",
  );

  return (
    <section className="entry-panel" aria-labelledby="add-record-title">
      <div className="section-heading">
        <div>
          <p className="section-kicker">Update your ledger</p>
          <h2 id="add-record-title">Add a finance record</h2>
        </div>
        <p>Every saved change appends an encrypted, auditable event.</p>
      </div>
      <div className="entry-grid">
        <details open={overview.categories.length === 0}>
          <summary>Category</summary>
          <form
            onSubmit={category.handleSubmit(async (values) => {
              const id = crypto.randomUUID();
              await dashboard.category.mutateAsync({
                idempotencyKey: `category-${id}`,
                body: {
                  category_id: `category-${id}`,
                  name: values.name,
                  direction: values.direction,
                  expected_version: overview.provenance.projection_version,
                },
              });
              category.reset();
            })}
          >
            <Field label="Name" error={category.formState.errors.name?.message}>
              <input autoComplete="off" {...category.register("name")} />
            </Field>
            <Field
              label="Type"
              error={category.formState.errors.direction?.message}
            >
              <select {...category.register("direction")}>
                <option value="expense">Expense</option>
                <option value="income">Income</option>
              </select>
            </Field>
            <SubmitButton pending={dashboard.category.isPending}>
              Save category
            </SubmitButton>
            <MutationError error={dashboard.category.error} />
          </form>
        </details>

        <details>
          <summary>Income or expense</summary>
          <form
            onSubmit={transaction.handleSubmit(async (values) => {
              const id = crypto.randomUUID();
              await dashboard.transaction.mutateAsync({
                idempotencyKey: `transaction-${id}`,
                body: {
                  transaction_id: `transaction-${id}`,
                  direction: values.direction,
                  category_id: values.category_id,
                  amount: {
                    currency: "USD",
                    minor_units: usdToMinorUnits(values.amount),
                  },
                  occurred_on: values.occurred_on,
                  description: values.description,
                  recurring_entry_id: null,
                  expected_version: overview.provenance.projection_version,
                },
              });
              transaction.reset({
                direction: values.direction,
                category_id: "",
                amount: "",
                occurred_on: currentDate(),
                description: "",
              });
            })}
          >
            <Field
              label="Type"
              error={transaction.formState.errors.direction?.message}
            >
              <select {...transaction.register("direction")}>
                <option value="expense">Expense</option>
                <option value="income">Income</option>
              </select>
            </Field>
            <CategoryField
              label="Category"
              categories={overview.categories.filter(
                (item) =>
                  item.active && item.direction === transactionDirection,
              )}
              registration={transaction.register("category_id")}
              error={transaction.formState.errors.category_id?.message}
            />
            <Field
              label="Amount in USD"
              error={transaction.formState.errors.amount?.message}
            >
              <input
                inputMode="decimal"
                placeholder="0.00"
                {...transaction.register("amount")}
              />
            </Field>
            <Field
              label="Date"
              error={transaction.formState.errors.occurred_on?.message}
            >
              <input type="date" {...transaction.register("occurred_on")} />
            </Field>
            <Field
              label="Description"
              error={transaction.formState.errors.description?.message}
            >
              <input
                autoComplete="off"
                {...transaction.register("description")}
              />
            </Field>
            <SubmitButton
              pending={dashboard.transaction.isPending}
              disabled={overview.categories.length === 0}
            >
              Save transaction
            </SubmitButton>
            {overview.categories.length === 0 && (
              <p className="form-hint">Create a matching category first.</p>
            )}
            <MutationError error={dashboard.transaction.error} />
          </form>
        </details>

        <details>
          <summary>Monthly budget</summary>
          <form
            onSubmit={budget.handleSubmit(async (values) => {
              const id = `${month}-${values.category_id}`;
              await dashboard.budget.mutateAsync({
                idempotencyKey: `budget-${crypto.randomUUID()}`,
                body: {
                  budget_id: `budget-${id}`,
                  category_id: values.category_id,
                  month,
                  limit: {
                    currency: "USD",
                    minor_units: usdToMinorUnits(values.amount),
                  },
                  expected_version: overview.provenance.projection_version,
                },
              });
              budget.reset();
            })}
          >
            <CategoryField
              label="Expense category"
              categories={expenseCategories}
              registration={budget.register("category_id")}
              error={budget.formState.errors.category_id?.message}
            />
            <Field
              label="Monthly limit in USD"
              error={budget.formState.errors.amount?.message}
            >
              <input
                inputMode="decimal"
                placeholder="0.00"
                {...budget.register("amount")}
              />
            </Field>
            <SubmitButton
              pending={dashboard.budget.isPending}
              disabled={expenseCategories.length === 0}
            >
              Save budget
            </SubmitButton>
            <MutationError error={dashboard.budget.error} />
          </form>
        </details>

        <details>
          <summary>Monthly recurring item</summary>
          <form
            onSubmit={recurring.handleSubmit(async (values) => {
              const id = crypto.randomUUID();
              await dashboard.recurring.mutateAsync({
                idempotencyKey: `recurring-${id}`,
                body: {
                  recurring_entry_id: `recurring-${id}`,
                  direction: values.direction,
                  category_id: values.category_id,
                  amount: {
                    currency: "USD",
                    minor_units: usdToMinorUnits(values.amount),
                  },
                  description: values.description,
                  cadence: "monthly",
                  starts_on: `${month}-01`,
                  ends_on: null,
                  expected_version: overview.provenance.projection_version,
                },
              });
              recurring.reset({
                direction: values.direction,
                category_id: "",
                amount: "",
                description: "",
              });
            })}
          >
            <Field
              label="Type"
              error={recurring.formState.errors.direction?.message}
            >
              <select {...recurring.register("direction")}>
                <option value="expense">Expense</option>
                <option value="income">Income</option>
              </select>
            </Field>
            <CategoryField
              label="Category"
              categories={overview.categories.filter(
                (item) => item.active && item.direction === recurringDirection,
              )}
              registration={recurring.register("category_id")}
              error={recurring.formState.errors.category_id?.message}
            />
            <Field
              label="Amount in USD"
              error={recurring.formState.errors.amount?.message}
            >
              <input
                inputMode="decimal"
                placeholder="0.00"
                {...recurring.register("amount")}
              />
            </Field>
            <Field
              label="Description"
              error={recurring.formState.errors.description?.message}
            >
              <input
                autoComplete="off"
                {...recurring.register("description")}
              />
            </Field>
            <SubmitButton
              pending={dashboard.recurring.isPending}
              disabled={overview.categories.length === 0}
            >
              Save recurring item
            </SubmitButton>
            <MutationError error={dashboard.recurring.error} />
          </form>
        </details>
      </div>
    </section>
  );
}

function Field({
  label,
  error,
  children,
}: {
  label: string;
  error?: string | undefined;
  children: React.ReactNode;
}) {
  return (
    <label className="form-field">
      <span>{label}</span>
      {children}
      {error !== undefined && <small className="field-error">{error}</small>}
    </label>
  );
}

function CategoryField({
  label,
  categories,
  registration,
  error,
}: {
  label: string;
  categories: FinanceOverview["categories"];
  registration: UseFormRegisterReturn;
  error?: string | undefined;
}) {
  return (
    <Field label={label} error={error}>
      <select {...registration}>
        <option value="">Choose category</option>
        {categories.map((category) => (
          <option key={category.category_id} value={category.category_id}>
            {category.name}
          </option>
        ))}
      </select>
    </Field>
  );
}

function SubmitButton({
  pending,
  disabled = false,
  children,
}: {
  pending: boolean;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      className="primary-button"
      type="submit"
      disabled={pending || disabled}
    >
      {pending ? "Saving…" : children}
    </button>
  );
}

function MutationError({ error }: { error: Error | null }) {
  return error === null ? null : (
    <p className="form-error" role="alert">
      {error.message}
    </p>
  );
}

function validAmount(value: string): boolean {
  try {
    usdToMinorUnits(value);
    return true;
  } catch {
    return false;
  }
}
