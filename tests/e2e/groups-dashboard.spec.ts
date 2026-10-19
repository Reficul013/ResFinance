import { expect, test, type Route } from "@playwright/test";

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
          source: "resvault",
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

  const members = page.locator(".members-panel");
  await expect(members.getByRole("heading", { name: "Members" })).toBeVisible();
  const alexRow = members.getByRole("listitem").filter({ hasText: "Alex" });
  const samRow = members.getByRole("listitem").filter({ hasText: "Sam" });
  await expect(alexRow.getByText("Owner", { exact: true })).toBeVisible();
  await expect(samRow.getByText("You", { exact: true })).toBeVisible();
  const alexAddress = alexRow.getByRole("tooltip");
  await expect(alexAddress).toBeHidden();
  await alexRow.locator(".member-name").hover();
  await expect(alexAddress).toBeVisible();
  await expect(alexAddress).toHaveText(creditor);
  await page.mouse.move(0, 0);
  await expect(alexAddress).toBeHidden();
  await samRow.locator(".member-name").focus();
  await expect(samRow.getByRole("tooltip")).toHaveText(debtor);
  await expect(samRow.getByRole("tooltip")).toBeVisible();

  await page.getByRole("button", { name: "Approve in ResVault" }).click();
  await expect(page.getByText("open", { exact: true })).toBeVisible();

  await page.getByLabel("Credit amount (USD units)").fill("60.00");
  await page
    .getByRole("button", { name: "Approve funding in ResVault" })
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
  await page.route("**/api/v1/auth/refresh", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        access_token: "groups-e2e-token",
        token_type: "Bearer",
        expires_at: "2026-10-14T18:00:00Z",
        actor_address: creditor,
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
  await expect(page.locator(".members-panel")).toHaveCount(0);
});

test("shows validation and signing failures inside the affected form", async ({
  page,
}) => {
  let commandRequests = 0;
  await page.addInitScript(() => {
    window.addEventListener("message", (event) => {
      const message = event.data as {
        source?: string;
        type?: string;
        request_id?: string;
      };
      if (
        message.source !== "resfinance-page" ||
        message.type !== "SIGN_INTENT"
      )
        return;
      window.postMessage(
        {
          source: "resvault",
          version: 1,
          request_id: message.request_id,
          ok: false,
          error: "User rejected the request in ResVault",
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
        actor_address: creditor,
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
        obligations: [],
        credit_balances: {},
        notifications: [],
        provenance: {
          projection_version: 2,
          as_of_utc: "2026-10-14T17:00:00Z",
          source_event_ids: ["evt-group", "evt-member"],
        },
        credit_disclaimer:
          "Internal credits are non-redeemable, non-monetary, and have no cash value.",
      }),
    });
  });
  await page.route("**/api/v1/groups/friends/**", async (route) => {
    commandRequests += 1;
    await route.abort();
  });

  await page.goto("/groups");
  const expenseForm = page.locator(".expense-form");
  await expect(
    expenseForm.getByRole("heading", { name: "Create signed expense" }),
  ).toBeVisible();

  await expenseForm.getByLabel("Description").fill("Dinner");
  await expenseForm.getByLabel("Total amount").fill("60.00");
  await expenseForm
    .getByLabel("Exact shares, one wallet=amount per line")
    .fill(`${creditor}=0.00\n${debtor}=60.00`);
  await expenseForm
    .getByRole("button", { name: "Approve split in ResVault" })
    .click();
  await expect(expenseForm.getByRole("alert")).toHaveText(
    "Amount must be greater than $0.00.",
  );

  await expenseForm
    .getByLabel("Exact shares, one wallet=amount per line")
    .fill(`${debtor}=60.00`);
  await expenseForm
    .getByRole("button", { name: "Approve split in ResVault" })
    .click();
  await expect(expenseForm.getByRole("alert")).toHaveText(
    "User rejected the request in ResVault",
  );

  const creditForm = page
    .locator("section")
    .filter({ hasText: "Fund internal credits" });
  await creditForm.getByLabel("Credit amount (USD units)").fill("0");
  await creditForm
    .getByRole("button", { name: "Approve funding in ResVault" })
    .click();
  await expect(creditForm.getByRole("alert")).toHaveText(
    "Amount must be greater than $0.00.",
  );
  await expect(expenseForm.getByRole("alert")).toHaveText(
    "User rejected the request in ResVault",
  );
  expect(commandRequests).toBe(0);
});

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
