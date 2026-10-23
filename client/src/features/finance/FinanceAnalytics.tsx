import {
  Area,
  AreaChart,
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
import {
  chartLegendWrapperStyle,
  chartTickStyle,
  chartTooltipContentStyle,
  chartTooltipCursor,
  chartTooltipItemStyle,
  chartTooltipLabelStyle,
} from "../../lib/chartTooltip";
import { useAnimateWhenVisible } from "../../lib/useAnimateWhenVisible";
import { buildMonthBalancePath, type BalancePathPoint } from "./balancePath";
import { formatUsd } from "./money";

const CHART_HEIGHT = 260;
const PIE_ANIMATION_MS = 900;
const PATH_ANIMATION_MS = 1100;
const LINE_ANIMATION_MS = 1200;

/** High-contrast teal / gold / red-coral map — fixed per category so slices stay distinct. */
const categoryColorByName: Record<string, string> = {
  "Food & Groceries": "#38d1c5",
  Utilities: "#f2bd5a",
  Entertainment: "#ff5c6c",
  "Medical Bills": "#e76f51",
  Rent: "#2bbbad",
  Shopping: "#ffb703",
  Miscellaneous: "#e63946",
};

const chartColorFallback = [
  "#38d1c5",
  "#f2bd5a",
  "#ff5c6c",
  "#e76f51",
  "#2bbbad",
  "#ffb703",
  "#e63946",
  "#8ecae6",
];

function categoryChartColor(name: string, index: number): string {
  return (
    categoryColorByName[name] ??
    chartColorFallback[index % chartColorFallback.length]!
  );
}

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
  const balancePath = buildMonthBalancePath(overview);
  const monthlyData = historyMonths.flatMap((month, index) => {
    const item = history[index];
    return item === undefined
      ? []
      : [
          {
            month,
            label: shortMonth(month),
            income: item.summary.income.minor_units,
            expenses: item.summary.expense.minor_units,
            savings: item.summary.savings.available.minor_units,
          },
        ];
  });

  return (
    <section className="finance-analytics" aria-labelledby="analytics-title">
      <div className="dashboard-section-heading">
        <div>
          <p className="section-kicker">Spending patterns</p>
          <h2 id="analytics-title">Your Financial Trends</h2>
          <p className="section-description">
            Charts use your recorded ledger and upcoming recurring commitments.
          </p>
        </div>
      </div>
      <div className="analytics-grid">
        <CategorySplitChart data={categoryData} />
        <BalancePathChart data={balancePath} />
        <CashFlowTrendChart data={monthlyData} />
      </div>
    </section>
  );
}

function CategorySplitChart({ data }: { data: CategoryDatum[] }) {
  const { ref, animated } = useAnimateWhenVisible<HTMLDivElement>();
  return (
    <ChartCard title="Spending By Category" description="This reporting month">
      {data.length === 0 ? (
        <EmptyChart text="Record an expense to see its category split." />
      ) : (
        <div
          ref={ref}
          className="analytics-chart"
          data-animated={animated ? "true" : "false"}
          role="img"
          aria-label={`Category spending: ${data.map((item) => `${item.name} ${formatUsd(item.amount)}`).join(", ")}`}
        >
          {data.length === 1 ? (
            <div className="single-category-chart">
              <span
                className="single-category-donut"
                style={{
                  background: `conic-gradient(${categoryChartColor(data[0]!.name, 0)} 0 100%)`,
                }}
                aria-hidden="true"
              />
              <span className="single-category-legend">
                <i
                  style={{
                    background: categoryChartColor(data[0]!.name, 0),
                  }}
                  aria-hidden="true"
                />
                <span>
                  <strong>{data[0]!.name}</strong>
                  <small>{formatUsd(data[0]!.amount)} · 100%</small>
                </span>
              </span>
            </div>
          ) : (
            <ResponsiveContainer
              key={animated ? "animated" : "idle"}
              width="100%"
              height={CHART_HEIGHT}
            >
              <PieChart>
                <Pie
                  data={data}
                  dataKey="amount"
                  nameKey="name"
                  cx="45%"
                  cy="50%"
                  innerRadius={46}
                  outerRadius={88}
                  paddingAngle={3}
                  stroke="var(--panel-background)"
                  strokeWidth={2}
                  isAnimationActive={animated}
                  animationBegin={0}
                  animationDuration={PIE_ANIMATION_MS}
                  animationEasing="ease-out"
                >
                  {data.map((item, index) => (
                    <Cell
                      key={item.categoryId}
                      fill={categoryChartColor(item.name, index)}
                    />
                  ))}
                </Pie>
                <Legend
                  layout="vertical"
                  verticalAlign="middle"
                  align="right"
                  wrapperStyle={chartLegendWrapperStyle}
                />
                <Tooltip
                  contentStyle={chartTooltipContentStyle}
                  labelStyle={chartTooltipLabelStyle}
                  itemStyle={chartTooltipItemStyle}
                  formatter={(value) => formatUsd(Number(value))}
                />
              </PieChart>
            </ResponsiveContainer>
          )}
        </div>
      )}
    </ChartCard>
  );
}

function BalancePathChart({ data }: { data: BalancePathPoint[] }) {
  const { ref, animated } = useAnimateWhenVisible<HTMLDivElement>();
  const ending = data.at(-1)?.balance;
  const balances = data.map((point) => point.balance);
  const dataMax = Math.max(0, ...balances);
  const dataMin = Math.min(0, ...balances);
  const pad = Math.max((dataMax - dataMin) * 0.12, 50_000);
  // Anchor the glow at the chart floor so fill sits under the whole step path,
  // not only the positive segment down to $0.
  const domainMin = dataMin - pad;
  const domainMax = dataMax + pad;
  return (
    <ChartCard
      title="Balance Through The Month"
      description="Running ledger balance by day"
    >
      {data.length === 0 ? (
        <EmptyChart text="Record a transaction to see the month's balance path." />
      ) : (
        <div
          ref={ref}
          className="analytics-chart balance-path-chart"
          data-animated={animated ? "true" : "false"}
          role="img"
          aria-label={`Balance Through The Month ending at ${formatUsd(ending ?? 0)}`}
        >
          <ResponsiveContainer
            key={animated ? "animated" : "idle"}
            width="100%"
            height={CHART_HEIGHT}
          >
            <AreaChart
              data={data}
              margin={{ top: 10, right: 8, left: 0, bottom: 0 }}
            >
              <defs>
                <linearGradient
                  id="balancePathFill"
                  x1="0"
                  y1="0"
                  x2="0"
                  y2="1"
                >
                  <stop
                    offset="0%"
                    stopColor="var(--income)"
                    stopOpacity={0.42}
                  >
                    {animated ? (
                      <animate
                        attributeName="stop-opacity"
                        values="0.2;0.65;0.2"
                        dur="2s"
                        repeatCount="indefinite"
                      />
                    ) : null}
                  </stop>
                  <stop
                    offset="55%"
                    stopColor="var(--income)"
                    stopOpacity={0.16}
                  >
                    {animated ? (
                      <animate
                        attributeName="stop-opacity"
                        values="0.05;0.34;0.05"
                        dur="2s"
                        repeatCount="indefinite"
                      />
                    ) : null}
                  </stop>
                  <stop
                    offset="100%"
                    stopColor="var(--income)"
                    stopOpacity={0.03}
                  />
                </linearGradient>
              </defs>
              <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
              <XAxis
                dataKey="label"
                tick={chartTickStyle}
                interval="preserveStartEnd"
                tickFormatter={(value: string) =>
                  Number(value) === 1 || Number(value) % 5 === 0 ? value : ""
                }
              />
              <YAxis
                domain={[domainMin, domainMax]}
                tick={chartTickStyle}
                tickFormatter={compactUsd}
                width={56}
              />
              <Tooltip
                cursor={chartTooltipCursor}
                contentStyle={chartTooltipContentStyle}
                labelStyle={chartTooltipLabelStyle}
                itemStyle={chartTooltipItemStyle}
                labelFormatter={(_label, payload) => {
                  const point = payload?.[0]?.payload as
                    | BalancePathPoint
                    | undefined;
                  return point?.date ?? "";
                }}
                formatter={(value) => [
                  formatUsd(Number(value)),
                  "Running balance",
                ]}
              />
              <Area
                type="stepAfter"
                dataKey="balance"
                name="Running balance"
                stroke="var(--income)"
                strokeWidth={2.75}
                fill="url(#balancePathFill)"
                baseValue={domainMin}
                dot={false}
                activeDot={{ r: 4 }}
                isAnimationActive={animated}
                animationBegin={0}
                animationDuration={PATH_ANIMATION_MS}
                animationEasing="ease-out"
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
    </ChartCard>
  );
}

function CashFlowTrendChart({ data }: { data: MonthlyDatum[] }) {
  const { ref, animated } = useAnimateWhenVisible<HTMLDivElement>();
  return (
    <ChartCard
      title="Cash Flow Over Time"
      description="Exactly six reporting months"
    >
      <div
        ref={ref}
        className="analytics-chart"
        data-animated={animated ? "true" : "false"}
        role="img"
        aria-label="Six month income, expenses, and available savings trend"
      >
        <ResponsiveContainer
          key={animated ? "animated" : "idle"}
          width="100%"
          height={CHART_HEIGHT}
        >
          <LineChart
            data={data}
            margin={{ top: 10, right: 8, left: 0, bottom: 0 }}
          >
            <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
            <XAxis dataKey="label" tick={chartTickStyle} />
            <YAxis tick={chartTickStyle} tickFormatter={compactUsd} />
            <Tooltip
              contentStyle={chartTooltipContentStyle}
              labelStyle={chartTooltipLabelStyle}
              itemStyle={chartTooltipItemStyle}
              formatter={(value) => formatUsd(Number(value))}
            />
            <Legend
              wrapperStyle={chartLegendWrapperStyle}
              itemSorter={(item) =>
                item.dataKey === "income"
                  ? 0
                  : item.dataKey === "expenses"
                    ? 1
                    : 2
              }
            />
            <Line
              type="monotone"
              dataKey="income"
              name="Income"
              stroke="var(--income)"
              strokeWidth={3}
              dot={{ r: 3 }}
              activeDot={{ r: 5 }}
              connectNulls
              isAnimationActive={animated}
              animationBegin={0}
              animationDuration={LINE_ANIMATION_MS}
              animationEasing="ease-out"
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
              isAnimationActive={animated}
              animationBegin={80}
              animationDuration={LINE_ANIMATION_MS}
              animationEasing="ease-out"
            />
            <Line
              type="monotone"
              dataKey="savings"
              name="Available savings"
              stroke="var(--warning)"
              strokeWidth={3}
              strokeDasharray="1 7"
              strokeLinecap="round"
              dot={{ r: 4 }}
              activeDot={{ r: 6 }}
              connectNulls
              isAnimationActive={animated}
              animationBegin={160}
              animationDuration={LINE_ANIMATION_MS}
              animationEasing="ease-out"
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
  income: number;
  expenses: number;
  savings: number;
}
