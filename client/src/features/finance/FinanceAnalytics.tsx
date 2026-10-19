import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { FinanceOverview } from "../../lib/api/client";
import { formatUsd } from "./money";

const chartColors = [
  "#4cc9f0",
  "#4361ee",
  "#7209b7",
  "#f72585",
  "#f77f00",
  "#43aa8b",
  "#f9c74f",
];

interface FinanceAnalyticsProps {
  overview: FinanceOverview;
  historyMonths: string[];
  history: Array<FinanceOverview | undefined>;
}

export function FinanceAnalytics({
  overview,
  historyMonths,
  history,
}: FinanceAnalyticsProps) {
  const categoryData = categorySpending(overview);
  const monthlyData = historyMonths.flatMap((month, index) => {
    const item = history[index];
    return item === undefined
      ? []
      : [
          {
            month,
            label: shortMonth(month),
            expenses: item.summary.expense.minor_units,
            savings: item.summary.savings.available.minor_units,
          },
        ];
  });

  return (
    <section className="finance-analytics" aria-labelledby="analytics-title">
      <div className="section-heading">
        <div>
          <p className="section-kicker">Spending patterns</p>
          <h2 id="analytics-title">Your financial trends</h2>
        </div>
        <p>
          Charts use your recorded ledger and upcoming recurring commitments.
        </p>
      </div>
      <div className="analytics-grid">
        <CategorySplitChart data={categoryData} />
        <CategoryTotalsChart data={categoryData} />
        <SavingsExpenseChart data={monthlyData} />
      </div>
    </section>
  );
}

function CategorySplitChart({ data }: { data: CategoryDatum[] }) {
  return (
    <ChartCard title="Spending by category" description="This reporting month">
      {data.length === 0 ? (
        <EmptyChart text="Record an expense to see its category split." />
      ) : (
        <div
          className="analytics-chart"
          role="img"
          aria-label={`Category spending: ${data.map((item) => `${item.name} ${formatUsd(item.amount)}`).join(", ")}`}
        >
          <ResponsiveContainer width="100%" height={260}>
            <PieChart>
              <Pie
                data={data}
                dataKey="amount"
                nameKey="name"
                cx="45%"
                cy="50%"
                innerRadius={46}
                outerRadius={88}
                paddingAngle={2}
              >
                {data.map((item, index) => (
                  <Cell
                    key={item.categoryId}
                    fill={chartColors[index % chartColors.length]}
                  />
                ))}
              </Pie>
              <Legend layout="vertical" verticalAlign="middle" align="right" />
              <Tooltip formatter={(value) => formatUsd(Number(value))} />
            </PieChart>
          </ResponsiveContainer>
        </div>
      )}
    </ChartCard>
  );
}

function CategoryTotalsChart({ data }: { data: CategoryDatum[] }) {
  return (
    <ChartCard title="Category totals" description="This reporting month">
      {data.length === 0 ? (
        <EmptyChart text="Record an expense to compare category totals." />
      ) : (
        <div
          className="analytics-chart"
          role="img"
          aria-label="Expense totals by category"
        >
          <ResponsiveContainer width="100%" height={260}>
            <BarChart
              data={data}
              margin={{ top: 10, right: 8, left: 0, bottom: 28 }}
            >
              <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
              <XAxis
                dataKey="name"
                angle={-28}
                textAnchor="end"
                interval={0}
                tick={{ fill: "var(--page-muted)", fontSize: 11 }}
              />
              <YAxis
                tick={{ fill: "var(--page-muted)", fontSize: 11 }}
                tickFormatter={compactUsd}
              />
              <Tooltip formatter={(value) => formatUsd(Number(value))} />
              <Bar
                dataKey="amount"
                name="Spending"
                fill="var(--expense)"
                radius={[7, 7, 2, 2]}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </ChartCard>
  );
}

function SavingsExpenseChart({ data }: { data: MonthlyDatum[] }) {
  return (
    <ChartCard
      title="Savings vs. expenses"
      description="Last six reporting months"
    >
      <div
        className="analytics-chart"
        role="img"
        aria-label="Six month savings and expenses comparison"
      >
        <ResponsiveContainer width="100%" height={260}>
          <LineChart
            data={data}
            margin={{ top: 10, right: 8, left: 0, bottom: 0 }}
          >
            <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
            <XAxis
              dataKey="label"
              tick={{ fill: "var(--page-muted)", fontSize: 11 }}
            />
            <YAxis
              tick={{ fill: "var(--page-muted)", fontSize: 11 }}
              tickFormatter={compactUsd}
            />
            <Tooltip formatter={(value) => formatUsd(Number(value))} />
            <Legend />
            <Line
              type="monotone"
              dataKey="savings"
              name="Savings"
              stroke="var(--page-accent)"
              strokeWidth={3}
              strokeDasharray="1 7"
              strokeLinecap="round"
              dot={{ r: 4 }}
              activeDot={{ r: 6 }}
              connectNulls
            />
            <Line
              type="monotone"
              dataKey="expenses"
              name="Expenses"
              stroke="var(--expense)"
              strokeWidth={3}
              strokeDasharray="1 7"
              strokeLinecap="round"
              dot={{ r: 4 }}
              activeDot={{ r: 6 }}
              connectNulls
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </ChartCard>
  );
}

function ChartCard({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <section className="panel analytics-card" aria-label={title}>
      <div className="section-heading compact">
        <div>
          <h3>{title}</h3>
          <p>{description}</p>
        </div>
      </div>
      {children}
    </section>
  );
}

function EmptyChart({ text }: { text: string }) {
  return <p className="empty-state analytics-empty">{text}</p>;
}

function categorySpending(overview: FinanceOverview): CategoryDatum[] {
  const categoryNames = new Map(
    overview.categories.map((item) => [item.category_id, item.name]),
  );
  const totals = new Map<string, number>();
  for (const entry of overview.transactions) {
    if (
      !entry.voided &&
      entry.direction === "expense" &&
      entry.occurred_on.startsWith(overview.summary.month)
    ) {
      totals.set(
        entry.category_id,
        (totals.get(entry.category_id) ?? 0) + entry.amount.minor_units,
      );
    }
  }
  return [...totals.entries()]
    .map(([categoryId, amount]) => ({
      categoryId,
      name: categoryNames.get(categoryId) ?? "Other",
      amount,
    }))
    .sort((left, right) => right.amount - left.amount);
}

function shortMonth(month: string): string {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    year: "2-digit",
    timeZone: "UTC",
  }).format(new Date(`${month}-01T00:00:00Z`));
}

function compactUsd(value: number): string {
  return new Intl.NumberFormat(undefined, {
    notation: "compact",
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value / 100);
}

interface CategoryDatum {
  [key: string]: string | number;
  categoryId: string;
  name: string;
  amount: number;
}

interface MonthlyDatum {
  month: string;
  label: string;
  expenses: number;
  savings: number;
}
