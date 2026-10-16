import {
  chromium,
  expect,
  test,
  type BrowserContext,
  type Page,
  type Request,
} from "@playwright/test";
import { execFileSync } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const enabled = process.env.RESFINANCE_LOCAL_HANDOFF === "1";
const root = resolve(process.cwd(), "..");
const extension = resolve(root, "resvault/dist");
const python = resolve(root, ".venv/bin/python");
const lifecycle = ["-m", "scripts.milestone9.local_handoff"];
const password = "local-handoff-only-password";

test.skip(!enabled, "run with npm run test:e2e:local against the Milestone 9 stack");

test("real ResVault and services preserve the local journey through restart", async () => {
  const first = await walletContext("owner");
  const second = await walletContext("member");
  try {
    const owner = await initializeWallet(first, "owner");
    const member = await initializeWallet(second, "member");
    console.log("milestone9:e2e wallets initialized");
    await proveWrongOriginHasNoExtension(first);
    const ownerPage = await authenticate(first);
    const memberPage = await authenticate(second);
    console.log("milestone9:e2e both sessions authenticated");

    await seedFinance(ownerPage);
    console.log("milestone9:e2e finance records saved");
    const groupName = await createAndSettleGroup(
      ownerPage,
      memberPage,
      member.address,
    );
    console.log("milestone9:e2e group settled with tamper and replay rejected");

    const financeProjection = waitForGet(ownerPage, /\/finance\/overview\?/);
    await ownerPage.getByRole("link", { name: "Personal Finance" }).click();
    const finance = (await (await financeProjection).json()) as {
      obligations: Array<{
        amount: { minor_units: number };
        contract_receipt: string;
        direction: string;
        settled: boolean;
      }>;
      summary: { savings: { available: { minor_units: number } } };
    };
    expect(finance.summary.savings.available.minor_units).toBe(400_000);
    expect(finance.obligations).toContainEqual(
      expect.objectContaining({
        amount: { currency: "USD", minor_units: 6_000 },
        direction: "receivable",
        settled: true,
        contract_receipt: expect.any(String),
      }),
    );

    const cryptoProjection = waitForGet(ownerPage, /\/crypto\/overview\?/);
    await ownerPage.getByRole("link", { name: "Crypto" }).click();
    const crypto = (await (await cryptoProjection).json()) as {
      default_capital: { minor_units: number };
      savings_formula_version: string;
      savings_source_event_ids: string[];
    };
    expect(crypto.default_capital.minor_units).toBe(400_000);
    expect(crypto.savings_formula_version).toBe("finance-savings-v1");
    expect(crypto.savings_source_event_ids.length).toBeGreaterThanOrEqual(2);
    await ownerPage.getByRole("button", { name: "Save risk profile" }).click();
    await expect(ownerPage.getByText(/Score 50/)).toBeVisible();
    await expect(
      ownerPage.getByRole("heading", { name: /No forecast is eligible/ }),
    ).toBeVisible();
    await ownerPage.getByLabel("Scenario amount (USD)").fill("2500.00");
    const gatedScenario = waitForPost(ownerPage, /\/crypto\/scenarios$/);
    await ownerPage.getByRole("button", { name: "Analyze amount" }).click();
    expect((await gatedScenario).status()).toBe(422);
    await expect(ownerPage.getByRole("alert")).toContainText(
      "no promoted forecast is available",
    );
    await ownerPage.getByRole("link", { name: "Personal Finance" }).click();
    const savingsCard = ownerPage
      .getByLabel("Finance summary")
      .locator("article")
      .filter({ hasText: "Available savings" });
    await expect(savingsCard).toContainText("$4,000.00");
    console.log("milestone9:e2e crypto gate verified");

    await ownerPage.getByRole("link", { name: "Smart Insights" }).click();
    await ownerPage.getByRole("textbox", { name: "Question" }).fill(
      "Which recorded budgets need attention?",
    );
    const budgetInsight = waitForPost(
      ownerPage,
      /\/insights\/query$/,
      120_000,
    );
    await ownerPage.getByRole("button", { name: "Explain" }).click();
    expect((await budgetInsight).status()).toBe(200);
    await expect(ownerPage.locator('[aria-label="Evidence used"]')).toBeVisible();
    await ownerPage.getByRole("textbox", { name: "Question" }).fill(
      "Transfer my crypto and settle everything for me",
    );
    const unsafeInsight = waitForPost(
      ownerPage,
      /\/insights\/query$/,
      120_000,
    );
    await ownerPage.getByRole("button", { name: "Explain" }).click();
    expect((await unsafeInsight).status()).toBe(200);
    await expect(
      ownerPage.getByRole("heading", { name: /I cannot write records/i }),
    ).toBeVisible();
    console.log("milestone9:e2e insight boundaries verified");

    const beforeRestart = await ownerPage.locator("main").innerText();
    execFileSync(python, [...lifecycle, "restart"], { cwd: root, stdio: "inherit" });
    console.log("milestone9:e2e stack restarted");
    await ownerPage.reload();
    await expect(ownerPage.getByRole("link", { name: "Personal Finance" })).toBeVisible({
      timeout: 90_000,
    });
    await ownerPage.getByRole("link", { name: "Friends & Groups" }).click();
    await selectGroup(ownerPage, groupName);
    await expect(ownerPage.getByText("$0.00 outstanding")).toBeVisible();
    await expect(ownerPage.getByText("settled", { exact: true })).toBeVisible();

    const loggedOut = ownerPage.waitForResponse(
      (response) =>
        response.request().method() === "DELETE" &&
        response.url().endsWith("/api/v1/auth/sessions/current"),
    );
    await ownerPage.getByRole("button", { name: "Log out" }).click();
    expect((await loggedOut).status()).toBe(204);
    await expect(ownerPage.getByRole("button", { name: "Connect wallet" })).toBeEnabled();
    await expectWalletLocked(first);
    await expect(ownerPage.locator("main")).not.toContainText(beforeRestart);
  } finally {
    await first.close();
    await second.close();
  }
});

async function walletContext(label: string): Promise<BrowserContext> {
  const profile = mkdtempSync(join(tmpdir(), `resfinance-${label}-`));
  const context = await chromium.launchPersistentContext(profile, {
    headless: false,
    args: [
      `--disable-extensions-except=${extension}`,
      `--load-extension=${extension}`,
    ],
  });
  const observeErrors = (page: Page) =>
    page.on("pageerror", (error) =>
      console.log(`milestone9:e2e pageerror ${page.url()} ${error.message}`),
    );
  context.pages().forEach(observeErrors);
  context.on("page", observeErrors);
  return context;
}

async function extensionId(context: BrowserContext): Promise<string> {
  let worker = context.serviceWorkers()[0];
  worker ??= await context.waitForEvent("serviceworker");
  return new URL(worker.url()).host;
}

async function initializeWallet(
  context: BrowserContext,
  label: string,
): Promise<{ address: string }> {
  const page = await context.newPage();
  await page.goto(`chrome-extension://${await extensionId(context)}/popup.html`);
  await page.locator("#setup-password").fill(password);
  await page.getByRole("button", { name: "Create ResVault" }).click();
  await expect(page.locator("#unlocked")).toBeVisible({ timeout: 30_000 });
  await expect(page.locator("#address")).not.toHaveText("");
  const address = (await page.locator("#address").textContent())?.trim();
  if (!address) throw new Error(`${label} wallet address was not created`);
  await page.close();
  return { address };
}

async function authenticate(context: BrowserContext): Promise<Page> {
  const page = await context.newPage();
  await page.goto("http://127.0.0.1:5173/finance");
  await expect(page.getByRole("button", { name: "Connect wallet" })).toBeEnabled();
  await approveAfter(context, () => page.getByRole("button", { name: "Connect wallet" }).click());
  await expect(page.getByRole("heading", { name: "Session active" })).toBeVisible();
  return page;
}

async function approveAfter(context: BrowserContext, action: () => Promise<unknown>) {
  await unlockWallet(context);
  const applicationPage = context
    .pages()
    .find((page) => page.url().startsWith("http://127.0.0.1:5173/"));
  if (applicationPage === undefined)
    throw new Error("ResFinance application page is unavailable");
  await expectExtensionAvailable(applicationPage);
  const popupPromise = context.waitForEvent("page", { timeout: 15_000 });
  await action();
  let approval: Page;
  try {
    approval = await popupPromise;
  } catch (error) {
    const diagnostics = await Promise.all(
      context.pages().map(async (page) => ({
        url: page.url(),
        text: await page.locator("body").innerText().catch(() => ""),
      })),
    );
    throw new Error(`ResVault approval did not open: ${JSON.stringify(diagnostics)}`, {
      cause: error,
    });
  }
  await approval.waitForLoadState("domcontentloaded");
  await approval.getByRole("button", { name: "Approve and sign" }).click();
}

async function unlockWallet(context: BrowserContext) {
  const page = await context.newPage();
  await page.goto(`chrome-extension://${await extensionId(context)}/popup.html`);
  if (await page.locator("#locked").isVisible()) {
    await page.locator("#unlock-password").fill(password);
    await page.getByRole("button", { name: "Unlock" }).click();
    await expect(page.locator("#unlocked")).toBeVisible({ timeout: 30_000 });
  }
  await page.close();
}

async function expectWalletLocked(context: BrowserContext) {
  const page = await context.newPage();
  await page.goto(`chrome-extension://${await extensionId(context)}/popup.html`);
  await expect(page.locator("#locked")).toBeVisible({ timeout: 30_000 });
  await page.close();
}

async function seedFinance(page: Page) {
  await expect(page.getByRole("heading", { name: "Your money, in one view." })).toBeVisible();
  const category = page.locator("details").filter({
    has: page.locator("summary").filter({ hasText: /^Category$/ }),
  });
  await category.getByLabel("Name").fill("Salary");
  await category.getByLabel("Type").selectOption("income");
  await submitFinanceWrite(page, "/finance/categories", () =>
    category.getByRole("button", { name: "Save category" }).click(),
  );
  await expect(category.getByLabel("Name")).toBeHidden();
  await category.locator("summary").click();
  await category.getByLabel("Name").fill("Housing");
  await category.getByLabel("Type").selectOption("expense");
  await submitFinanceWrite(page, "/finance/categories", () =>
    category.getByRole("button", { name: "Save category" }).click(),
  );

  const transaction = page.locator("details").filter({
    has: page.locator("summary").filter({ hasText: /^Income or expense$/ }),
  });
  await transaction.locator("summary").click();
  await transaction.getByLabel("Type").selectOption("income");
  await transaction.getByLabel("Category").selectOption({ label: "Salary" });
  await transaction.getByLabel("Amount in USD").fill("5000.00");
  await transaction.getByLabel("Description").fill("Local handoff income");
  await submitFinanceWrite(page, "/finance/transactions", () =>
    transaction.getByRole("button", { name: "Save transaction" }).click(),
  );
  await transaction.getByLabel("Type").selectOption("expense");
  await transaction.getByLabel("Category").selectOption({ label: "Housing" });
  await transaction.getByLabel("Amount in USD").fill("1000.00");
  await transaction.getByLabel("Description").fill("Local handoff rent");
  await submitFinanceWrite(page, "/finance/transactions", () =>
    transaction.getByRole("button", { name: "Save transaction" }).click(),
  );

  const budget = page.locator("details").filter({
    has: page.locator("summary").filter({ hasText: /^Monthly budget$/ }),
  });
  await budget.locator("summary").click();
  await budget.getByLabel("Expense category").selectOption({ label: "Housing" });
  await budget.getByLabel("Monthly limit in USD").fill("1200.00");
  await submitFinanceWrite(page, "/finance/budgets", () =>
    budget.getByRole("button", { name: "Save budget" }).click(),
  );
}

async function submitFinanceWrite(
  page: Page,
  endpoint: string,
  submit: () => Promise<unknown>,
) {
  const write = page.waitForResponse(
    (response) =>
      response.url().includes(endpoint) &&
      response.request().method() === "POST",
  );
  const refreshed = page.waitForResponse(
    (response) =>
      response.url().includes("/finance/overview") &&
      response.request().method() === "GET" &&
      response.status() === 200,
  );
  await submit();
  const response = await write;
  expect(response.status(), await response.text()).toBe(201);
  await refreshed;
}

async function createAndSettleGroup(
  owner: Page,
  member: Page,
  memberAddress: string,
) {
  const groupName = `Local Handoff ${crypto.randomUUID().slice(0, 8)}`;
  await owner.getByRole("link", { name: "Friends & Groups" }).click();
  await owner.getByLabel("Group name").fill(groupName);
  await owner.getByLabel("Your display name").fill("Owner");
  const groupCreated = owner.waitForResponse(
    (response) =>
      response.url().endsWith("/api/v1/groups") &&
      response.request().method() === "POST",
  );
  await owner.getByRole("button", { name: "Create group" }).click();
  expect((await groupCreated).status()).toBe(201);
  await owner.getByLabel("Wallet address").fill(memberAddress);
  await owner.getByLabel("Display name", { exact: true }).fill("Member");
  const memberCreated = owner.waitForResponse(
    (response) =>
      response.url().endsWith("/members") &&
      response.request().method() === "POST",
  );
  const groupRefreshed = owner.waitForResponse(
    (response) =>
      /\/api\/v1\/groups\/group-[^/]+$/.test(response.url()) &&
      response.request().method() === "GET" &&
      response.status() === 200,
  );
  await owner.getByRole("button", { name: "Add member" }).click();
  expect((await memberCreated).status()).toBe(201);
  await groupRefreshed;
  await owner.getByLabel("Description").fill("Shared dinner");
  await owner.getByLabel("Total amount").fill("60.00");
  await owner.getByLabel("Exact shares, one wallet=amount per line").fill(
    `${memberAddress}=60.00`,
  );
  const expenseButton = owner.getByRole("button", {
    name: "Approve split in ResVault",
  });
  expect(
    await expenseButton
      .locator("xpath=ancestor::form")
      .evaluate((form: HTMLFormElement) => form.checkValidity()),
  ).toBe(true);
  await expectExtensionAvailable(owner);
  const expenseCreated = waitForPost(owner, /\/expenses$/);
  const expenseProjection = waitForGroupProjection(owner);
  await approveAfter(owner.context(), () =>
    expenseButton.click(),
  );
  expect((await expenseCreated).status()).toBe(201);
  await expenseProjection;
  await expect(owner.getByText("$60.00 outstanding")).toBeVisible();

  await member.reload();
  await expect(member.getByRole("heading", { name: "Session active" })).toBeVisible();
  await member.getByRole("link", { name: "Friends & Groups" }).click();
  await selectGroup(member, groupName);
  const decisionCreated = waitForPost(member, /\/decision$/);
  const decisionProjection = waitForGroupProjection(member);
  await approveAfter(member.context(), () =>
    member.getByRole("button", { name: "Approve in ResVault" }).click(),
  );
  expect((await decisionCreated).status()).toBe(201);
  await decisionProjection;
  await member.getByLabel("Credit amount (USD units)").fill("60.00");
  const fundingRequestPromise = member.waitForRequest(
    (request) => request.method() === "POST" && request.url().endsWith("/credits"),
  );
  const fundingCreated = waitForPost(member, /\/credits$/);
  const fundingProjection = waitForGroupProjection(member);
  await approveAfter(member.context(), () =>
    member.getByRole("button", { name: "Approve funding in ResVault" }).click(),
  );
  const fundingRequest = await fundingRequestPromise;
  expect((await fundingCreated).status()).toBe(201);
  await fundingProjection;
  await proveTamperAndReplayRejection(member, fundingRequest);
  await member.getByLabel("Partial or full amount").fill("20.00");
  const partialSettlement = waitForPost(member, /\/settlements$/);
  const partialProjection = waitForGroupProjection(member);
  await approveAfter(member.context(), () =>
    member.getByRole("button", { name: "Settle with credits" }).click(),
  );
  expect((await partialSettlement).status()).toBe(201);
  await partialProjection;
  await expect(member.getByText("$40.00 outstanding")).toBeVisible();
  await member.getByLabel("Partial or full amount").fill("40.00");
  const finalSettlement = waitForPost(member, /\/settlements$/);
  const finalProjection = waitForGroupProjection(member);
  await approveAfter(member.context(), () =>
    member.getByRole("button", { name: "Settle with credits" }).click(),
  );
  expect((await finalSettlement).status()).toBe(201);
  await finalProjection;
  await expect(member.getByText("$0.00 outstanding")).toBeVisible();
  return groupName;
}

async function selectGroup(page: Page, groupName: string) {
  await page
    .getByRole("navigation", { name: "Your groups" })
    .getByRole("button")
    .filter({ hasText: groupName })
    .click();
}

function waitForPost(page: Page, endpoint: RegExp, timeout = 30_000) {
  return page.waitForResponse(
    (response) =>
      response.request().method() === "POST" && endpoint.test(response.url()),
    { timeout },
  );
}

function waitForGet(page: Page, endpoint: RegExp, timeout = 30_000) {
  return page.waitForResponse(
    (response) =>
      response.request().method() === "GET" &&
      endpoint.test(response.url()) &&
      response.status() === 200,
    { timeout },
  );
}

function waitForGroupProjection(page: Page) {
  return page.waitForResponse(
    (response) =>
      response.request().method() === "GET" &&
      /\/api\/v1\/groups\/group-[^/]+$/.test(response.url()) &&
      response.status() === 200,
    { timeout: 120_000 },
  );
}

async function proveTamperAndReplayRejection(page: Page, request: Request) {
  const url = request.url();
  const headers = await request.allHeaders();
  const original = JSON.parse(request.postData() ?? "{}") as {
    amount: { minor_units: number };
  };
  const authorization = headers.authorization;
  if (!authorization) throw new Error("funding request omitted its access token");
  const tampered = structuredClone(original);
  tampered.amount.minor_units += 1;
  const statuses = await page.evaluate(
    async ({ endpoint, accessToken, body, replayBody }) => {
      const send = (value: object, idempotency: string) =>
        fetch(endpoint, {
          method: "POST",
          credentials: "include",
          headers: {
            Accept: "application/json",
            Authorization: accessToken,
            "Content-Type": "application/json",
            "Idempotency-Key": idempotency,
          },
          body: JSON.stringify(value),
        });
      const tamper = await send(body, `tamper-${crypto.randomUUID()}`);
      const replay = await send(replayBody, `replay-${crypto.randomUUID()}`);
      return [tamper.status, replay.status];
    },
    {
      endpoint: url,
      accessToken: authorization,
      body: tampered,
      replayBody: original,
    },
  );
  expect(statuses).toEqual([422, 422]);
}

async function proveWrongOriginHasNoExtension(context: BrowserContext) {
  const page = await context.newPage();
  await page.goto("http://127.0.0.1:8000/api/v1/health");
  const answered = await page.evaluate(
    () =>
      new Promise<boolean>((resolve) => {
        const requestId = crypto.randomUUID();
        const timer = window.setTimeout(() => resolve(false), 750);
        window.addEventListener("message", (event) => {
          const value = event.data as { source?: string; request_id?: string };
          if (value.source === "resvault" && value.request_id === requestId) {
            window.clearTimeout(timer);
            resolve(true);
          }
        });
        window.postMessage(
          {
            source: "resfinance-page",
            version: 1,
            request_id: requestId,
            type: "GET_IDENTITY",
          },
          window.location.origin,
        );
      }),
  );
  expect(answered).toBe(false);
  await page.close();
}

async function expectExtensionAvailable(page: Page) {
  const response = await page.evaluate(
    () =>
      new Promise<{ ok?: boolean; error?: string }>((resolve) => {
        const requestId = crypto.randomUUID();
        const timer = window.setTimeout(
          () => resolve({ error: "extension response timed out" }),
          2_000,
        );
        window.addEventListener("message", (event) => {
          const value = event.data as {
            source?: string;
            request_id?: string;
            ok?: boolean;
            error?: string;
          };
          if (value.source === "resvault" && value.request_id === requestId) {
            window.clearTimeout(timer);
            resolve(value);
          }
        });
        window.postMessage(
          {
            source: "resfinance-page",
            version: 1,
            request_id: requestId,
            type: "GET_IDENTITY",
          },
          window.location.origin,
        );
      }),
  );
  expect(response, response.error).toMatchObject({ ok: true });
}
