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
