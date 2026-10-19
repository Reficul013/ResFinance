import { expect, test } from "@playwright/test";

const overview = {
  summary: {
    month: "2026-10",
    income: { currency: "USD", minor_units: 500000 },
    expense: { currency: "USD", minor_units: 90000 },
    balance: { currency: "USD", minor_units: 410000 },
    receivable: { currency: "USD", minor_units: 30000 },
    payable: { currency: "USD", minor_units: 20000 },
    outstanding_recurring_income: { currency: "USD", minor_units: 0 },
    outstanding_recurring_expense: { currency: "USD", minor_units: 150000 },
    savings: {
      actual: { currency: "USD", minor_units: 410000 },
      projected: { currency: "USD", minor_units: 270000 },
      available: { currency: "USD", minor_units: 270000 },
      formula_version: "finance-savings-v1",
      calculation_id: "savings_e2e",
      source_event_ids: [
        "evt_income",
        "evt_expense",
        "evt_recurring",
        "evt_payable",
        "evt_receivable",
      ],
    },
    budget_statuses: [
      {
        budget_id: "budget-groceries",
        category_id: "groceries",
        category_name: "Groceries",
        limit: { currency: "USD", minor_units: 100000 },
        spent: { currency: "USD", minor_units: 90000 },
        remaining: { currency: "USD", minor_units: 10000 },
        utilization_basis_points: 9000,
        status: "near_limit",
        source_event_ids: ["evt_budget", "evt_expense"],
      },
    ],
  },
  categories: [
    {
      category_id: "salary",
      name: "Salary",
      direction: "income",
      active: true,
      source_event_id: "evt_category_income",
    },
    {
      category_id: "groceries",
      name: "Groceries",
      direction: "expense",
      active: true,
      source_event_id: "evt_category_expense",
    },
  ],
  transactions: [
    {
      transaction_id: "paycheck",
      direction: "income",
      category_id: "salary",
      amount: { currency: "USD", minor_units: 500000 },
      occurred_on: "2026-10-01",
      description: "October salary",
      recurring_entry_id: null,
      voided: false,
      source_event_id: "evt_income",
    },
    {
      transaction_id: "groceries",
      direction: "expense",
      category_id: "groceries",
      amount: { currency: "USD", minor_units: 90000 },
      occurred_on: "2026-10-10",
      description: "October groceries",
      recurring_entry_id: null,
      voided: false,
      source_event_id: "evt_expense",
    },
  ],
  budgets: [
    {
      budget_id: "budget-groceries",
      category_id: "groceries",
      month: "2026-10",
      limit: { currency: "USD", minor_units: 100000 },
      source_event_id: "evt_budget",
    },
  ],
  recurring_entries: [
    {
      recurring_entry_id: "monthly-groceries",
      direction: "expense",
      category_id: "groceries",
      amount: { currency: "USD", minor_units: 150000 },
      description: "Expected monthly groceries",
      cadence: "monthly",
      starts_on: "2026-01-01",
      ends_on: null,
      active: true,
      source_event_id: "evt_recurring",
    },
  ],
  obligations: [
    {
      obligation_id: "group-payable",
      direction: "payable",
      amount: { currency: "USD", minor_units: 20000 },
      due_on: "2026-10-20",
      settled: false,
      source_event_id: "evt_payable",
      contract_receipt: "receipt_1",
    },
    {
      obligation_id: "group-receivable",
      direction: "receivable",
      amount: { currency: "USD", minor_units: 30000 },
      due_on: "2026-10-22",
      settled: false,
      source_event_id: "evt_receivable",
      contract_receipt: "receipt_2",
    },
  ],
  provenance: {
    projection_version: 8,
    as_of_utc: "2026-10-14T08:00:00Z",
    source_event_ids: [
      "evt_category_income",
      "evt_category_expense",
      "evt_income",
      "evt_expense",
      "evt_budget",
      "evt_recurring",
      "evt_payable",
      "evt_receivable",
    ],
  },
};

test("renders exact balances, budget alert, savings, and provenance", async ({
  page,
}) => {
  await page.route("**/api/v1/auth/refresh", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        access_token: "e2e-access-token",
        token_type: "Bearer",
        expires_at: "2026-10-14T08:10:00Z",
        actor_address: `0x${"a".repeat(40)}`,
      }),
    });
  });
  await page.route("**/api/v1/health", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "ok", service: "resfinance-api" }),
    });
  });
  await page.route("**/api/v1/auth/sessions/current", async (route) => {
    await route.fulfill({ status: 204 });
  });
  await page.route("**/api/v1/finance/overview?month=*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(overview),
    });
  });

  await page.goto("/finance");

  await expect(
    page.getByRole("heading", { name: "Your money, in one view." }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Switch to Light Mode" }),
  ).toBeVisible();
  const topBar = page.locator(".auth-card");
  await expect(
    topBar.getByRole("heading", { name: "ResFinance" }),
  ).toBeVisible();
  await expect(topBar.locator(".auth-brand-logo-light")).toHaveAttribute(
    "src",
    "/favicon.png",
  );
  await expect(topBar.locator(".auth-brand-logo-dark")).toHaveAttribute(
    "src",
    "/favicon-dark.png",
  );
  await expect(topBar.locator(".auth-brand-logo-dark")).toBeVisible();
  await expect(topBar.locator(".auth-brand-logo-light")).not.toBeVisible();
  const dashboardNavigation = topBar.getByRole("navigation", {
    name: "ResFinance dashboards",
  });
  await expect(dashboardNavigation.getByRole("link")).toHaveCount(4);
  await expect(
    dashboardNavigation.getByRole("link", { name: "Personal Finance" }),
  ).toHaveAttribute("aria-current", "page");
  await expect(topBar.getByLabel("No in-app notifications")).toBeVisible();
  await expect(topBar.locator(".notification-bell")).toBeVisible();
  await expect(topBar.locator(".auth-action-icon")).toBeVisible();
  await expect(topBar.locator(".theme-slider-track")).toBeVisible();
  await expect(topBar.getByText("Log out", { exact: true })).toHaveCount(0);
  await expect(topBar.getByText(/^(Light|Dark) Mode$/)).toHaveCount(0);
  await expect(page.getByText(/milestone/i)).toHaveCount(0);
  await expect(page.locator('link[rel="icon"]')).toHaveAttribute(
    "href",
    "/favicon.png",
  );
  const sessionCardBox = await page.locator(".auth-card").boundingBox();
  const logoutButtonBox = await page
    .getByRole("button", { name: "Log out" })
    .boundingBox();
  const notificationButtonBox = await topBar
    .getByLabel("No in-app notifications")
    .boundingBox();
  const notificationBellBox = await topBar
    .locator(".notification-bell")
    .boundingBox();
  const dashboardNavigationBox = await dashboardNavigation.boundingBox();
  const themeToggleBox = await page
    .getByRole("button", { name: "Switch to Light Mode" })
    .boundingBox();
  expect(sessionCardBox).not.toBeNull();
  expect(logoutButtonBox).not.toBeNull();
  expect(notificationButtonBox).not.toBeNull();
  expect(notificationBellBox).not.toBeNull();
  expect(dashboardNavigationBox).not.toBeNull();
  expect(themeToggleBox).not.toBeNull();
  expect(dashboardNavigationBox!.width).toBeGreaterThan(550);
  expect(themeToggleBox!.x + themeToggleBox!.width).toBeLessThanOrEqual(
    notificationButtonBox!.x,
  );
  expect(
    notificationButtonBox!.x + notificationButtonBox!.width,
  ).toBeLessThanOrEqual(logoutButtonBox!.x);
  expect(
    notificationButtonBox!.width - notificationBellBox!.width,
  ).toBeGreaterThanOrEqual(16);
  expect(logoutButtonBox!.x + logoutButtonBox!.width).toBeLessThanOrEqual(
    sessionCardBox!.x + sessionCardBox!.width,
  );
  expect(
    Math.abs(themeToggleBox!.height - notificationButtonBox!.height),
  ).toBeLessThanOrEqual(1);
  expect(
    Math.abs(themeToggleBox!.height - logoutButtonBox!.height),
  ).toBeLessThanOrEqual(1);
  expect(themeToggleBox!.y).toBeGreaterThanOrEqual(sessionCardBox!.y);
  expect(themeToggleBox!.y + themeToggleBox!.height).toBeLessThanOrEqual(
    sessionCardBox!.y + sessionCardBox!.height,
  );
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(page.locator(".theme-toggle")).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await page.getByRole("button", { name: "Switch to Light Mode" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expect(topBar.locator(".auth-brand-logo-light")).toBeVisible();
  await expect(topBar.locator(".auth-brand-logo-dark")).not.toBeVisible();
  await expect(page.locator(".theme-toggle")).toHaveAttribute(
    "aria-pressed",
    "false",
  );
  await page.screenshot({
    path: "test-results/finance-dashboard-light.png",
    fullPage: false,
  });
  await expect(
    page.getByRole("button", { name: "Switch to Dark Mode" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Switch to Dark Mode" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(topBar.locator(".auth-brand-logo-dark")).toBeVisible();

  await page.setViewportSize({ width: 375, height: 812 });
  const compactSessionCardBox = await page.locator(".auth-card").boundingBox();
  const compactThemeToggleBox = await page
    .getByRole("button", { name: "Switch to Light Mode" })
    .boundingBox();
  expect(compactSessionCardBox).not.toBeNull();
  expect(compactThemeToggleBox).not.toBeNull();
  expect(
    compactThemeToggleBox!.x + compactThemeToggleBox!.width,
  ).toBeLessThanOrEqual(
    compactSessionCardBox!.x + compactSessionCardBox!.width,
  );
  expect(compactThemeToggleBox!.y).toBeGreaterThanOrEqual(
    compactSessionCardBox!.y,
  );
  expect(
    compactThemeToggleBox!.y + compactThemeToggleBox!.height,
  ).toBeLessThanOrEqual(
    compactSessionCardBox!.y + compactSessionCardBox!.height,
  );
  await page.screenshot({
    path: "test-results/finance-dashboard-mobile.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 1280, height: 720 });
  await expect(page.getByText("$4,100.00", { exact: true })).toBeVisible();
  await expect(page.getByText("$5,000.00", { exact: true })).toBeVisible();
  await expect(
    page.getByText("$900.00", { exact: true }).first(),
  ).toBeVisible();
  await expect(page.getByText("$2,700.00", { exact: true })).toBeVisible();
  await expect(page.getByText("Near the limit")).toBeVisible();
  await expect(
    page.getByRole("progressbar", { name: "Groceries budget utilization" }),
  ).toHaveAttribute("value", "9000");
  await expect(
    page.getByRole("img", { name: /Income \$5,000.00/ }),
  ).toBeVisible();

  await page.getByText("Data freshness", { exact: true }).click();
  await expect(page.getByText(/^Updated /)).toBeVisible();
  await expect(page.getByText("Based on 8 verified records.")).toBeVisible();
  await expect(page.getByText(/Projection v8/)).toHaveCount(0);
  await expect(page.getByText("finance-savings-v1")).toHaveCount(0);
  await expect(page.getByText("savings_e2e")).toHaveCount(0);
  await page.screenshot({
    path: "test-results/finance-dashboard.png",
    fullPage: true,
  });

  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL("http://127.0.0.1:4173/");
  await expect(
    page.getByText("Private finance · Read-only insights"),
  ).toHaveCount(0);
  await expect(page.locator(".status-card")).toHaveCount(0);
  await page.screenshot({
    path: "test-results/logged-out-screen.png",
    fullPage: false,
  });
});
