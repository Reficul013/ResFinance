import {
  expect,
  test,
  type Locator,
  type Page,
  type Route,
} from "@playwright/test";

const debtor = `0x${"b".repeat(40)}`;
const creditor = `0x${"a".repeat(40)}`;
const obligationId = "obl-dinner-sam";

test("approves and settles an obligation partially and fully", async ({
  page,
}) => {
  let projectionVersion = 1;
  let status = "pending";
  let settled = 0;
  let debtorCredits = 0;
  let creditorCredits = 0;

  await page.addInitScript(() => {
    window.addEventListener("message", (event) => {
      const message = event.data as {
        source?: string;
        type?: string;
        request_id?: string;
        intent?: Record<string, unknown>;
      };
      if (
        message.source !== "resfinance-page" ||
        message.type !== "SIGN_INTENT"
      )
        return;
      const intent = message.intent!;
      window.postMessage(
        {
          source: "reswallet",
          version: 1,
          request_id: message.request_id,
          ok: true,
          result: {
            version: 1,
            intent_id: intent.intent_id,
            action: intent.action,
            actor_public_key: "e2e-public-key",
            actor_address: `0x${"b".repeat(40)}`,
            resource_id: intent.resource_id,
            parameters_hash: intent.parameters_hash,
            nonce: intent.nonce,
            issued_at: intent.issued_at,
            expires_at: intent.expires_at,
            origin: intent.origin,
            audience: intent.audience,
            network_id: intent.network_id,
            signature: "e2e-signature",
          },
        },
        window.location.origin,
      );
    });
  });

  await page.route("**/api/v1/auth/refresh", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        access_token: "groups-e2e-token",
        token_type: "Bearer",
        expires_at: "2026-10-14T18:00:00Z",
        actor_address: debtor,
      }),
    }),
  );
  await page.route("**/api/v1/health", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "ok", service: "resfinance-api" }),
    }),
  );
  await page.route("**/api/v1/groups", async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          group_id: "friends",
          name: "Friends",
          member_count: 2,
          open_obligation_count: status === "settled" ? 0 : 1,
          projection_version: projectionVersion,
        },
      ]),
    });
  });
  await page.route("**/api/v1/groups/friends", async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(groupOverview()),
    });
  });
  await page.route("**/api/v1/groups/friends/credits", async (route) => {
    const body = route.request().postDataJSON() as {
      amount: { minor_units: number };
    };
    debtorCredits += body.amount.minor_units;
    projectionVersion += 1;
    await commandResponse(route, "credits");
  });
  await page.route(
    `**/api/v1/groups/friends/obligations/${obligationId}/decision`,
    async (route) => {
      status = "open";
      projectionVersion += 1;
      await commandResponse(route, "approve");
    },
  );
  await page.route(
    `**/api/v1/groups/friends/obligations/${obligationId}/settlements`,
    async (route) => {
      const body = route.request().postDataJSON() as {
        amount: { minor_units: number };
      };
      settled += body.amount.minor_units;
      debtorCredits -= body.amount.minor_units;
      creditorCredits += body.amount.minor_units;
      status = settled === 6000 ? "settled" : "partially_settled";
      projectionVersion += 1;
      await commandResponse(route, "settlement");
    },
  );

  await page.goto("/groups");
  await expect(
    page.getByRole("heading", {
      name: "Shared expenses, signed by every participant.",
    }),
  ).toBeVisible();
  await expect(page.getByText("$60.00 outstanding")).toBeVisible();

  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
  const membersButton = page.getByRole("button", { name: /^2 members/ });
  const membersPopover = page.getByRole("dialog", { name: "Group members" });
  await expect(membersButton).toHaveAttribute("aria-expanded", "false");
  await expect(membersPopover).toHaveCount(0);

  await membersButton.click();
  await expect(membersPopover).toBeVisible();
  await expect(membersButton).toHaveAttribute("aria-expanded", "true");
  const alexRow = membersPopover
    .getByRole("listitem")
    .filter({ hasText: "Alex" });
  const samRow = membersPopover
    .getByRole("listitem")
    .filter({ hasText: "Sam" });
  await expect(alexRow.getByText("Owner", { exact: true })).toBeVisible();
  await expect(samRow.getByText("You", { exact: true })).toBeVisible();
  await expect(alexRow.locator("code")).toHaveText("0xaaaaaa…aaaaaa");
  await expect(alexRow.locator("code")).toHaveAttribute("title", creditor);

  await alexRow
    .getByRole("button", { name: "Copy Alex's wallet address" })
    .click();
  await expect(alexRow.getByRole("button", { name: /Copy Alex/ })).toHaveText(
    "Copied",
  );
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
    creditor,
  );

  await expectInsideViewport(page, membersPopover);
  await page.screenshot({ path: "test-results/groups-members-popover.png" });

  await page.keyboard.press("Escape");
  await expect(membersPopover).toHaveCount(0);
  await expect(membersButton).toBeFocused();

  const desktopViewport = page.viewportSize()!;
  await page.setViewportSize({ width: 390, height: 844 });
  await membersButton.click();
  await expectInsideViewport(page, membersPopover);
  await page.screenshot({
    path: "test-results/groups-members-popover-mobile.png",
  });
  await page.keyboard.press("Escape");
  await page.setViewportSize(desktopViewport);

  await membersButton.click();
  await expect(membersPopover).toBeVisible();
  await page
    .getByRole("heading", {
      name: "Shared expenses, signed by every participant.",
    })
    .click();
  await expect(membersPopover).toHaveCount(0);

  await page.getByRole("button", { name: "Approve in ResWallet" }).click();
  await expect(page.getByText("open", { exact: true })).toBeVisible();

  await page.getByLabel("Credit amount (USD units)").fill("60.00");
  await page
    .getByRole("button", { name: "Approve funding in ResWallet" })
    .click();
  await expect(page.getByText("$60.00", { exact: true })).toBeVisible();

  await page.getByLabel("Partial or full amount").fill("20.00");
  await page.getByRole("button", { name: "Settle with credits" }).click();
  await expect(page.getByText("$40.00 outstanding")).toBeVisible();
  await expect(
    page.getByText("partially settled", { exact: true }),
  ).toBeVisible();

  await page.getByLabel("Partial or full amount").fill("40.00");
  await page.getByRole("button", { name: "Settle with credits" }).click();
  await expect(page.getByText("$0.00 outstanding")).toBeVisible();
  await expect(page.getByText("settled", { exact: true })).toBeVisible();
  await expect(page.getByText(/non-redeemable, non-monetary/)).toBeVisible();
  await expect(page.getByText("Data Freshness and Provenance")).toBeVisible();
  await expect(
    page.locator(".group-overview").getByText("Projection", { exact: true }),
  ).toHaveCount(0);
  await expect(page.getByText(/Projection v5/)).toBeVisible();
  await expect(page.getByText(/5 encrypted source events/)).toBeVisible();
  await page.screenshot({
    path: "test-results/groups-dashboard.png",
    fullPage: true,
  });

  function groupOverview() {
    return {
      group_id: "friends",
      name: "Friends",
      owner_address: creditor,
      members: [
        {
          actor_address: creditor,
          display_name: "Alex",
          active: true,
          source_event_id: "evt-group",
        },
        {
          actor_address: debtor,
          display_name: "Sam",
          active: true,
          source_event_id: "evt-member",
        },
      ],
      expenses: [],
      obligations: [
        {
          obligation_id: obligationId,
          expense_id: "dinner",
          creditor_address: creditor,
          debtor_address: debtor,
          amount: { currency: "USD", minor_units: 6000 },
          settled_amount: { currency: "USD", minor_units: settled },
          outstanding_amount: { currency: "USD", minor_units: 6000 - settled },
          due_on: "2026-10-31",
          status,
          source_event_id: `evt-${projectionVersion}`,
          contract_receipts: ["receipt-create"],
        },
      ],
      credit_balances: {
        [debtor]: { currency: "USD", minor_units: debtorCredits },
        [creditor]: { currency: "USD", minor_units: creditorCredits },
      },
      notifications: [],
      provenance: {
        projection_version: projectionVersion,
        as_of_utc: "2026-10-14T17:00:00Z",
        source_event_ids: Array.from(
          { length: projectionVersion },
          (_, index) => `evt-${index + 1}`,
        ),
      },
      credit_disclaimer:
        "Internal credits are non-redeemable, non-monetary, and have no cash value.",
    };
  }
});

test("explains what to do when the user has no groups", async ({ page }) => {
  await mockSession(page, creditor);
  await page.route("**/api/v1/groups", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([]),
    }),
  );

  await page.goto("/groups");
  await expect(
    page.getByText(/No groups yet\. Create one above/),
  ).toBeVisible();
  await expect(page.locator(".members-menu")).toHaveCount(0);
});

test("shows validation and signing failures inside the affected form", async ({
  page,
}) => {
  let commandRequests = 0;
  await mockVault(page, {
    ok: false,
    error: "User rejected the request in ResWallet",
  });
  await mockSession(page, creditor);
  await mockGroup(page, [
    { address: creditor, name: "Alex" },
    { address: debtor, name: "Sam" },
  ]);
  await page.route("**/api/v1/groups/friends/**", async (route) => {
    commandRequests += 1;
    await route.abort();
  });

  await page.goto("/groups");
  const expenseForm = page.locator(".expense-form");
  await expect(
    expenseForm.getByRole("heading", { name: "Add an expense" }),
  ).toBeVisible();

  await expenseForm.getByLabel("Description").fill("Dinner");
  await expenseForm.getByLabel("Total amount").fill("60.00");
  await expenseForm.getByLabel("Exact amounts").check();
  await expenseForm.getByLabel("Alex's share").fill("0.00");
  await expenseForm.getByLabel("Sam's share").fill("60.00");
  await expenseForm
    .getByRole("button", { name: "Approve split in ResWallet" })
    .click();
  await expect(expenseForm.getByRole("alert")).toHaveText(
    "Alex's share: Amount must be greater than $0.00.",
  );

  await expenseForm.getByLabel("Include Alex").uncheck();
  await expect(expenseForm.getByText("All $60.00 assigned.")).toBeVisible();
  await expenseForm
    .getByRole("button", { name: "Approve split in ResWallet" })
    .click();
  await expect(expenseForm.getByRole("alert")).toHaveText(
    "User rejected the request in ResWallet",
  );

  const creditForm = page
    .locator("section")
    .filter({ hasText: "Fund internal credits" });
  await creditForm.getByLabel("Credit amount (USD units)").fill("0");
  await creditForm
    .getByRole("button", { name: "Approve funding in ResWallet" })
    .click();
  await expect(creditForm.getByRole("alert")).toHaveText(
    "Amount must be greater than $0.00.",
  );
  await expect(expenseForm.getByRole("alert")).toHaveText(
    "User rejected the request in ResWallet",
  );
  expect(commandRequests).toBe(0);
});

test("splits an expense equally between the selected members by default", async ({
  page,
}) => {
  const posted = await mockSplitGroup(page);
  await page.goto("/groups");
  const expenseForm = page.locator(".expense-form");
  await expect(expenseForm.getByText("Paid by you (Alex).")).toBeVisible();
  await expect(expenseForm.getByLabel("Split equally")).toBeChecked();
  await expect(expenseForm.getByLabel("Include Alex")).toBeChecked();
  await expect(expenseForm.getByLabel("Include Sam")).toBeChecked();
  await expect(expenseForm.getByLabel("Include Priya")).toBeChecked();
  await expect(
    expenseForm.getByText("Enter the total to split it equally."),
  ).toBeVisible();

  await expenseForm.getByLabel("Description").fill("Dinner");
  await expenseForm.getByLabel("Total amount").fill("90.00");
  for (const name of ["Alex", "Sam", "Priya"])
    await expect(expenseForm.getByLabel(`${name}'s share`)).toHaveText(
      "$30.00",
    );
  await expect(
    expenseForm.getByText(
      "All $90.00 assigned, split equally between 3 people.",
    ),
  ).toBeVisible();

  await expenseForm.getByLabel("Include Priya").uncheck();
  await expect(expenseForm.getByLabel("Alex's share")).toHaveText("$45.00");
  await expect(expenseForm.getByLabel("Sam's share")).toHaveText("$45.00");
  await expect(expenseForm.getByLabel("Priya's share")).toHaveText(
    "Not included",
  );

  await expenseForm.getByLabel("Total amount").fill("10.01");
  await expect(expenseForm.getByLabel("Alex's share")).toHaveText("$5.01");
  await expect(expenseForm.getByLabel("Sam's share")).toHaveText("$5.00");
  await expect(
    expenseForm.getByText(
      "All $10.01 assigned, split equally between 2 people.",
    ),
  ).toBeVisible();

  const samName = expenseForm
    .locator(".split-member")
    .filter({ hasText: "Sam" });
  await samName.locator(".member-name").hover();
  await expect(samName.getByRole("tooltip")).toBeVisible();
  await expect(samName.getByRole("tooltip")).toHaveText(debtor);
  await expenseForm.screenshot({
    path: "test-results/groups-expense-split-equal.png",
  });

  await expenseForm
    .getByRole("button", { name: "Approve split in ResWallet" })
    .click();
  await expect.poll(() => posted.length).toBe(1);
  const body = posted[0]!;
  expect(body.payer_address).toBe(creditor);
  expect(body.description).toBe("Dinner");
  expect(body.amount).toEqual({ currency: "USD", minor_units: 1001 });
  expect(body.shares).toEqual({
    [creditor]: { currency: "USD", minor_units: 501 },
    [debtor]: { currency: "USD", minor_units: 500 },
  });
  expect(body.intent.action).toBe("split.approve");
  expect(body.intent.resource_id).toBe(body.expense_id);

  await expect(expenseForm.getByLabel("Description")).toHaveValue("");
  await expect(expenseForm.getByLabel("Include Priya")).toBeChecked();
  await expect(expenseForm.getByLabel("Split equally")).toBeChecked();
  await expect(expenseForm.getByRole("alert")).toHaveCount(0);
});

test("lets the payer adjust an equal split into exact amounts", async ({
  page,
}) => {
  const posted = await mockSplitGroup(page);
  await page.goto("/groups");
  const expenseForm = page.locator(".expense-form");
  await expenseForm.getByLabel("Description").fill("Groceries");
  await expenseForm.getByLabel("Total amount").fill("90.00");

  await expenseForm.getByLabel("Exact amounts").check();
  for (const name of ["Alex", "Sam", "Priya"])
    await expect(expenseForm.getByLabel(`${name}'s share`)).toHaveValue(
      "30.00",
    );
  await expect(expenseForm.getByText("All $90.00 assigned.")).toBeVisible();

  await expenseForm.getByLabel("Include Priya").uncheck();
  await expect(expenseForm.getByLabel("Priya's share")).toBeDisabled();
  await expect(expenseForm.getByLabel("Priya's share")).toHaveValue("");
  await expect(
    expenseForm.getByText("$60.00 of $90.00 assigned · $30.00 left"),
  ).toBeVisible();

  await expenseForm.getByLabel("Sam's share").fill("70.00");
  await expect(
    expenseForm.getByText("$100.00 of $90.00 assigned · $10.00 over"),
  ).toBeVisible();
  await expenseForm.getByLabel("Sam's share").fill("60.00");
  await expect(expenseForm.getByText("All $90.00 assigned.")).toBeVisible();
  await expenseForm.screenshot({
    path: "test-results/groups-expense-split-exact.png",
  });

  await expenseForm
    .getByRole("button", { name: "Approve split in ResWallet" })
    .click();
  await expect.poll(() => posted.length).toBe(1);
  expect(posted[0]!.amount).toEqual({ currency: "USD", minor_units: 9000 });
  expect(posted[0]!.shares).toEqual({
    [creditor]: { currency: "USD", minor_units: 3000 },
    [debtor]: { currency: "USD", minor_units: 6000 },
  });

  await expect(expenseForm.getByLabel("Split equally")).toBeChecked();
  await expect(expenseForm.getByLabel("Include Priya")).toBeChecked();
});

async function mockSplitGroup(page: Page): Promise<ExpenseRequest[]> {
  const posted: ExpenseRequest[] = [];
  await mockVault(page, { ok: true, actorAddress: creditor });
  await mockSession(page, creditor);
  await mockGroup(page, [
    { address: creditor, name: "Alex" },
    { address: debtor, name: "Sam" },
    { address: `0x${"c".repeat(40)}`, name: "Priya" },
  ]);
  await page.route("**/api/v1/groups/friends/expenses", async (route) => {
    posted.push(route.request().postDataJSON() as ExpenseRequest);
    await commandResponse(route, "expense");
  });
  return posted;
}

interface ExpenseRequest {
  expense_id: string;
  payer_address: string;
  description: string;
  amount: { currency: string; minor_units: number };
  shares: Record<string, { currency: string; minor_units: number }>;
  intent: { action: string; resource_id: string };
}

type VaultOutcome =
  { ok: true; actorAddress: string } | { ok: false; error: string };

async function mockVault(page: Page, outcome: VaultOutcome) {
  await page.addInitScript((outcome: VaultOutcome) => {
    window.addEventListener("message", (event) => {
      const message = event.data as {
        source?: string;
        type?: string;
        request_id?: string;
        intent?: Record<string, unknown>;
      };
      if (
        message.source !== "resfinance-page" ||
        message.type !== "SIGN_INTENT"
      )
        return;
      const intent = message.intent!;
      window.postMessage(
        outcome.ok
          ? {
              source: "reswallet",
              version: 1,
              request_id: message.request_id,
              ok: true,
              result: {
                version: 1,
                intent_id: intent.intent_id,
                action: intent.action,
                actor_public_key: "e2e-public-key",
                actor_address: outcome.actorAddress,
                resource_id: intent.resource_id,
                parameters_hash: intent.parameters_hash,
                nonce: intent.nonce,
                issued_at: intent.issued_at,
                expires_at: intent.expires_at,
                origin: intent.origin,
                audience: intent.audience,
                network_id: intent.network_id,
                signature: "e2e-signature",
              },
            }
          : {
              source: "reswallet",
              version: 1,
              request_id: message.request_id,
              ok: false,
              error: outcome.error,
            },
        window.location.origin,
      );
    });
  }, outcome);
}

async function mockSession(page: Page, actorAddress: string) {
  await page.route("**/api/v1/auth/refresh", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        access_token: "groups-e2e-token",
        token_type: "Bearer",
        expires_at: "2026-10-14T18:00:00Z",
        actor_address: actorAddress,
      }),
    }),
  );
  await page.route("**/api/v1/health", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "ok", service: "resfinance-api" }),
    }),
  );
}

async function mockGroup(
  page: Page,
  members: { address: string; name: string }[],
) {
  await page.route("**/api/v1/groups", async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          group_id: "friends",
          name: "Friends",
          member_count: members.length,
          open_obligation_count: 0,
          projection_version: 2,
        },
      ]),
    });
  });
  await page.route("**/api/v1/groups/friends", async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        group_id: "friends",
        name: "Friends",
        owner_address: members[0]!.address,
        members: members.map((member, index) => ({
          actor_address: member.address,
          display_name: member.name,
          active: true,
          source_event_id: `evt-member-${index}`,
        })),
        expenses: [],
        obligations: [],
        credit_balances: {},
        notifications: [],
        provenance: {
          projection_version: 2,
          as_of_utc: "2026-10-14T17:00:00Z",
          source_event_ids: members.map((_, index) => `evt-member-${index}`),
        },
        credit_disclaimer:
          "Internal credits are non-redeemable, non-monetary, and have no cash value.",
      }),
    });
  });
}

async function expectInsideViewport(page: Page, locator: Locator) {
  await locator.scrollIntoViewIfNeeded();
  const box = await locator.boundingBox();
  const viewport = page.viewportSize()!;
  expect(box).not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(viewport.width);
}

async function commandResponse(route: Route, label: string) {
  await route.fulfill({
    status: 201,
    contentType: "application/json",
    body: JSON.stringify({
      event_id: `evt-${label}`,
      projection_version: 1,
      occurred_at_utc: "2026-10-14T17:00:00Z",
      deduplicated: false,
      receipt_ids: [`receipt-${label}`],
    }),
  });
}
