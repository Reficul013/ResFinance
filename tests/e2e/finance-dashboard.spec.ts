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
  await page.route("**/api/v1/insights/overview?month=*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        month: "2026-10",
        fact_bundle_id: "facts_finance_e2e",
        insight: {
          summary: "Your recorded budget is on track for this month.",
          evidence: [],
          caveats: ["This is a read-only explanation of recorded data."],
          follow_up_questions: ["How can I improve my savings?"],
          mode: "template-fallback",
          model_id: "template",
          model_revision: "finance-e2e",
          refused: false,
        },
        notifications: [],
      }),
    });
  });

  await page.goto("/finance");

  await expect(
    page.getByRole("heading", { name: "Your money, in one view." }),
  ).toBeVisible();
  await expect(
    page.locator("summary").filter({ hasText: /^Category$/ }),
  ).toHaveCount(0);
  const transactionForm = page.locator("details").filter({
    has: page.locator("summary").filter({ hasText: /^Income or expense$/ }),
  });
  await transactionForm.locator("summary").click();
  await expect(
    transactionForm.getByLabel("Category").locator("option"),
  ).toHaveText([
    "Choose category",
    "Rent",
    "Utilities",
    "Shopping",
    "Entertainment",
    "Food & Groceries",
    "Medical Bills",
    "Miscellaneous",
  ]);
  await transactionForm.getByLabel("Type").selectOption("income");
  await expect(
    transactionForm.getByLabel("Category").locator("option"),
  ).toHaveText([
    "Choose category",
    "Salary",
    "Liquid Funds Transfer",
    "Other Sources",
  ]);
  await expect(
    page.getByRole("button", { name: "Switch to Light Mode" }),
  ).toBeVisible();
  const topBar = page.locator(".auth-card");
  await expect(
    topBar.getByRole("heading", { name: "ResFinance" }),
  ).toBeVisible();
  const homeButton = topBar.getByRole("button", {
    name: "ResFinance",
    exact: true,
  });
  await expect(homeButton).toHaveAttribute(
    "title",
    "Log out and return to the ResFinance welcome screen",
  );
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
  await expect(dashboardNavigation.getByRole("link")).toHaveCount(3);
  await expect(
    dashboardNavigation.getByRole("link", { name: "Personal Finance" }),
  ).toHaveAttribute("aria-current", "page");
  await expect(topBar.getByLabel("No in-app notifications")).toBeVisible();
  await expect(topBar.locator(".notification-bell")).toBeVisible();
  const githubLink = topBar.getByRole("link", {
    name: "Open ResFinance repository on GitHub",
  });
  await expect(githubLink).toHaveAttribute(
    "href",
    "https://github.com/haseebshaik00/ResFinance",
  );
  await expect(githubLink).toHaveAttribute("target", "_blank");
  await expect(githubLink.locator(".github-icon")).toBeVisible();
  await expect(
    topBar
      .getByRole("button", { name: "Log out" })
      .locator(".auth-action-icon"),
  ).toBeVisible();
  await expect(topBar.locator(".theme-slider-track")).toBeVisible();
  await expect(topBar.getByText("Log out", { exact: true })).toHaveCount(0);
  await expect(topBar.getByText(/^(Light|Dark) Mode$/)).toHaveCount(0);
  await expect(page.getByText(/milestone/i)).toHaveCount(0);
  await expect(page.locator('link[rel="icon"]')).toHaveAttribute(
    "href",
    "/favicon.png",
  );
  const sessionCardBox = await page.locator(".auth-card").boundingBox();
  const githubLinkBox = await githubLink.boundingBox();
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
  expect(githubLinkBox).not.toBeNull();
  expect(logoutButtonBox).not.toBeNull();
  expect(notificationButtonBox).not.toBeNull();
  expect(notificationBellBox).not.toBeNull();
  expect(dashboardNavigationBox).not.toBeNull();
  expect(themeToggleBox).not.toBeNull();
  expect(dashboardNavigationBox!.width).toBeGreaterThan(450);
  expect(githubLinkBox!.x + githubLinkBox!.width).toBeLessThanOrEqual(
    themeToggleBox!.x,
  );
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
    Math.abs(githubLinkBox!.height - themeToggleBox!.height),
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
  await expect(
    page.getByRole("heading", { name: "Your financial trends" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Spending by category" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Category totals" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Savings vs. expenses" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Savings outlook" }),
  ).toHaveCount(0);
  const analyticsCards = page.locator(".analytics-grid > .analytics-card");
  await expect(analyticsCards).toHaveCount(3);
  const analyticsCardTopEdges = await analyticsCards.evaluateAll((cards) =>
    cards.map((card) => Math.round(card.getBoundingClientRect().top)),
  );
  expect(new Set(analyticsCardTopEdges).size).toBe(1);
  const savingsExpenseCard = page.locator(".analytics-card", {
    has: page.getByRole("heading", { name: "Savings vs. expenses" }),
  });
  await expect(savingsExpenseCard.locator(".recharts-line")).toHaveCount(2);
  await expect(savingsExpenseCard.locator(".recharts-bar")).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "Smart Savings Insights" }),
  ).toBeVisible();
  const entryFollowsSummary = await page
    .locator(".summary-grid")
    .evaluate((node) =>
      Boolean(
        node.compareDocumentPosition(
          document.querySelector(".entry-panel") as Node,
        ) & Node.DOCUMENT_POSITION_FOLLOWING,
      ),
    );
  expect(entryFollowsSummary).toBe(true);
  const chartsFollowEntry = await page
    .locator(".entry-panel")
    .evaluate((node) =>
      Boolean(
        node.compareDocumentPosition(
          document.querySelector(".dashboard-columns") as Node,
        ) & Node.DOCUMENT_POSITION_FOLLOWING,
      ),
    );
  expect(chartsFollowEntry).toBe(true);
  await expect(
    page.locator(".chart-panel").getByText("Projection v8", { exact: true }),
  ).toHaveCount(0);
  await expect(
    page
      .locator(".summary-grid")
      .getByText("finance-savings-v1", { exact: true }),
  ).toHaveCount(0);

  await expect(
    page.locator(".finance-dashboard > .provenance-panel"),
  ).toHaveCount(1);
  await page.locator(".finance-dashboard > .provenance-panel summary").click();
  await expect(
    page.getByRole("heading", { name: "Finance Insights" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Savings Insights", exact: true }),
  ).toBeVisible();
  const financeProvenanceBox = await page
    .getByRole("heading", { name: "Finance Insights" })
    .boundingBox();
  const savingsProvenanceBox = await page
    .getByRole("heading", { name: "Savings Insights", exact: true })
    .boundingBox();
  expect(financeProvenanceBox).not.toBeNull();
  expect(savingsProvenanceBox).not.toBeNull();
  expect(savingsProvenanceBox!.x).toBeGreaterThan(financeProvenanceBox!.x);
  expect(
    Math.abs(savingsProvenanceBox!.y - financeProvenanceBox!.y),
  ).toBeLessThan(2);
  await expect(page.getByText(/Projection v8 rebuilt through/)).toBeVisible();
  await expect(page.getByText(/Fact bundle facts_finance_e2e/)).toBeVisible();
  await expect(
    page.getByText("finance-savings-v1", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("savings_e2e")).toBeVisible();
  await expect(page.getByText(/5 source event/)).toBeVisible();
  await page.screenshot({
    path: "test-results/finance-dashboard.png",
    fullPage: true,
  });

  await homeButton.click();
  await expect(page).toHaveURL("http://127.0.0.1:4173/");
  await expect(
    page.getByRole("heading", { name: "ResFinance", level: 1 }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Connect ResVault" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Your money, in one view." }),
  ).toHaveCount(0);

  await page.goto("/finance");
  await expect(
    page.getByRole("heading", { name: "Your money, in one view." }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL("http://127.0.0.1:4173/");
  await expect(
    page.getByRole("heading", { name: "ResFinance", level: 1 }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Connect ResVault" }),
  ).toBeVisible();
  await expect(
    page.getByText("Private finance · Read-only insights"),
  ).toHaveCount(0);
  await expect(page.locator(".status-card")).toHaveCount(0);
  await page.screenshot({
    path: "test-results/logged-out-screen.png",
    fullPage: false,
  });
});

test("voids transactions and deactivates recurring items through confirmed audit events", async ({
  page,
}) => {
  const currentOverview = structuredClone(overview);

  await page.route("**/api/v1/auth/refresh", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        access_token: "e2e-access-token",
        token_type: "Bearer",
        expires_at: "2026-10-19T20:10:00Z",
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
  await page.route("**/api/v1/insights/overview?month=*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        month: "2026-10",
        fact_bundle_id: "facts_finance_actions",
        insight: {
          summary: "Your recorded budget is on track for this month.",
          evidence: [],
          caveats: [],
          follow_up_questions: [],
          mode: "template-fallback",
          model_id: "template",
          model_revision: "finance-actions",
          refused: false,
        },
        notifications: [],
      }),
    });
  });
  await page.route("**/api/v1/finance/overview?month=*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(currentOverview),
    });
  });

  let voidRequest: Record<string, unknown> | null = null;
  await page.route(
    "**/api/v1/finance/transactions/groceries/void",
    async (route) => {
      voidRequest = route.request().postDataJSON() as Record<string, unknown>;
      currentOverview.transactions[1].voided = true;
      currentOverview.summary.expense.minor_units = 0;
      currentOverview.summary.balance.minor_units = 500000;
      currentOverview.summary.savings.actual.minor_units = 500000;
      currentOverview.provenance.projection_version = 9;
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          event_id: "evt_void_expense",
          projection_version: 9,
          occurred_at_utc: "2026-10-19T20:00:00Z",
          deduplicated: false,
          receipt_ids: [],
        }),
      });
    },
  );

  let deactivateRequest: Record<string, unknown> | null = null;
  await page.route(
    "**/api/v1/finance/recurring/monthly-groceries/deactivate",
    async (route) => {
      deactivateRequest = route.request().postDataJSON() as Record<
        string,
        unknown
      >;
      currentOverview.recurring_entries[0].active = false;
      currentOverview.provenance.projection_version = 10;
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          event_id: "evt_deactivate_recurring",
          projection_version: 10,
          occurred_at_utc: "2026-10-19T20:01:00Z",
          deduplicated: false,
          receipt_ids: [],
        }),
      });
    },
  );

  await page.goto("/finance");

  const voidButton = page.getByRole("button", {
    name: "Void transaction October groceries",
  });
  const actionsHeadingBox = await page
    .getByRole("columnheader", { name: "Actions" })
    .boundingBox();
  const voidButtonBox = await voidButton.boundingBox();
  expect(actionsHeadingBox).not.toBeNull();
  expect(voidButtonBox).not.toBeNull();
  expect(
    Math.abs(
      actionsHeadingBox!.x +
        actionsHeadingBox!.width / 2 -
        (voidButtonBox!.x + voidButtonBox!.width / 2),
    ),
  ).toBeLessThanOrEqual(1);
  await expect(voidButton.locator(".lucide-archive-x")).toHaveAttribute(
    "stroke",
    "#FF6B4A",
  );
  await expect(voidButton.locator(".lucide-archive-x")).toHaveAttribute(
    "width",
    "18",
  );
  await voidButton.click();
  const voidDialog = page.getByRole("dialog", {
    name: "Void this transaction?",
  });
  await expect(voidDialog).toBeVisible();
  await expect(
    voidDialog.getByText(
      /original record remains in the append-only audit trail/i,
    ),
  ).toBeVisible();
  await expect(
    voidDialog.getByRole("button", { name: "Void Transaction" }),
  ).toBeDisabled();
  await voidDialog
    .getByLabel("Reason for voiding")
    .fill("Duplicate transaction");
  await voidDialog.getByRole("button", { name: "Void Transaction" }).click();

  await expect(
    page.getByText("October groceries", { exact: true }),
  ).toHaveCount(0);
  expect(voidRequest).toEqual({
    reason: "Duplicate transaction",
    expected_version: 8,
  });
  await expect(
    page.locator(".metric-card").filter({ hasText: "Expenses" }),
  ).toContainText("$0.00");

  const deactivateButton = page.getByRole("button", {
    name: "Deactivate recurring item Expected monthly groceries",
  });
  await expect(deactivateButton.locator(".lucide-archive-x")).toHaveAttribute(
    "stroke",
    "#FF6B4A",
  );
  await expect(deactivateButton.locator(".lucide-archive-x")).toHaveAttribute(
    "width",
    "18",
  );
  await deactivateButton.click();
  const deactivateDialog = page.getByRole("dialog", {
    name: "Deactivate this recurring item?",
  });
  await expect(deactivateDialog).toBeVisible();
  await deactivateDialog
    .getByRole("button", { name: "Deactivate Recurring Item" })
    .click();

  await expect(
    page.getByText("Expected monthly groceries", { exact: true }),
  ).toHaveCount(0);
  expect(deactivateRequest).toEqual({ expected_version: 9 });
});

test("updates the ResVault login guidance when the extension unlocks", async ({
  page,
}) => {
  await page.route("**/api/v1/auth/refresh", async (route) => {
    await route.fulfill({ status: 401 });
  });
  await page.addInitScript(() => {
    const identity = {
      public_key: "e2e-public-key",
      address: `0x${"6".repeat(40)}`,
    };
    window.addEventListener("message", (event) => {
      const request = event.data as {
        source?: string;
        version?: number;
        request_id?: string;
        type?: string;
      };
      if (
        event.source !== window ||
        request.source !== "resfinance-page" ||
        request.version !== 1 ||
        request.type !== "GET_STATUS"
      ) {
        return;
      }
      window.postMessage(
        {
          source: "resvault",
          version: 1,
          request_id: request.request_id,
          ok: true,
          result: { exists: true, unlocked: false, identity },
        },
        window.location.origin,
      );
    });
  });

  await page.goto("/");

  await expect(page.getByText("ResVault is locked.")).toBeVisible();
  await expect(page.locator(".auth-status-bulb")).toBeVisible();
  await expect(page.getByText("Your Wallet Address:")).toBeVisible();
  await expect(page.locator(".wallet-address")).toHaveText(
    `0x${"6".repeat(40)}`,
  );
  await expect(
    page.getByRole("button", { name: "Connect wallet" }),
  ).toBeDisabled();

  const helpButton = page.getByRole("button", {
    name: "How to connect ResVault",
  });
  await helpButton.hover();
  await expect(page.getByRole("tooltip")).toContainText(
    "Install and enable the hardened ResVault extension",
  );
  await expect(page.getByRole("tooltip")).toContainText("Approve & Login");
  await page.waitForTimeout(200);
  await page.screenshot({
    path: "test-results/resvault-login-help.png",
    fullPage: false,
  });

  const githubLink = page.getByRole("link", {
    name: "Open ResFinance repository on GitHub",
  });
  const themeToggle = page.getByRole("button", {
    name: "Switch to Light Mode",
  });
  const githubBox = await githubLink.boundingBox();
  const themeBox = await themeToggle.boundingBox();
  expect(githubBox).not.toBeNull();
  expect(themeBox).not.toBeNull();
  expect(githubBox!.x + githubBox!.width).toBeLessThanOrEqual(themeBox!.x);

  await page.evaluate(() => {
    window.postMessage(
      {
        source: "resvault",
        version: 1,
        type: "STATUS_CHANGED",
        status: {
          exists: true,
          unlocked: true,
          identity: {
            public_key: "e2e-public-key",
            address: `0x${"6".repeat(40)}`,
          },
        },
      },
      window.location.origin,
    );
  });

  await expect(
    page.getByText(
      "ResVault Detected! Unlock via extension and connect to wallet.",
    ),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Connect wallet" }),
  ).toBeEnabled();
  await page.mouse.move(0, 0);
  await expect(page.getByRole("tooltip")).not.toBeVisible();
  await page.screenshot({
    path: "test-results/resvault-login-ready.png",
    fullPage: false,
  });
});
