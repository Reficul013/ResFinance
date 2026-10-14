import type { components, paths } from "./generated/schema";
import type {
  SignedIntent,
  WalletIdentity,
} from "../../features/auth/resvault";

type HealthResponse =
  paths["/api/v1/health"]["get"]["responses"][200]["content"]["application/json"];

export async function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const request: RequestInit = { headers: { Accept: "application/json" } };
  if (signal !== undefined) {
    request.signal = signal;
  }
  const response = await fetch("/api/v1/health", request);
  if (!response.ok) {
    throw new Error(`Health request failed with ${response.status}`);
  }
  return (await response.json()) as HealthResponse;
}

type ChallengeResponse =
  paths["/api/v1/auth/challenges"]["post"]["responses"][201]["content"]["application/json"];
type SessionResponse =
  paths["/api/v1/auth/sessions"]["post"]["responses"][201]["content"]["application/json"];
type RefreshResponse =
  paths["/api/v1/auth/refresh"]["post"]["responses"][200]["content"]["application/json"];

export type FinanceOverview = components["schemas"]["FinanceOverviewModel"];
export type CategoryCommand = components["schemas"]["CategoryCommand"];
export type TransactionCommand = components["schemas"]["TransactionCommand"];
export type BudgetCommand = components["schemas"]["BudgetCommand"];
export type RecurringEntryCommand =
  components["schemas"]["RecurringEntryCommand"];
export type FinanceEvent = components["schemas"]["EventResponse"];

export async function createChallenge(
  identity: WalletIdentity,
): Promise<ChallengeResponse> {
  return requestJson<ChallengeResponse>("/api/v1/auth/challenges", {
    method: "POST",
    headers: jsonHeaders(),
    credentials: "include",
    body: JSON.stringify({ wallet: identity }),
  });
}

export async function createSession(
  challenge: string,
  intent: SignedIntent,
): Promise<SessionResponse> {
  return requestJson<SessionResponse>("/api/v1/auth/sessions", {
    method: "POST",
    headers: jsonHeaders(),
    credentials: "include",
    body: JSON.stringify({ challenge, intent }),
  });
}

export async function refreshSession(): Promise<RefreshResponse> {
  return requestJson<RefreshResponse>("/api/v1/auth/refresh", {
    method: "POST",
    headers: { Accept: "application/json" },
    credentials: "include",
  });
}

export async function logoutSession(accessToken: string): Promise<void> {
  const response = await fetch("/api/v1/auth/sessions/current", {
    method: "DELETE",
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    credentials: "include",
  });
  if (!response.ok) throw new Error(await problemMessage(response));
}

export async function getFinanceOverview(
  accessToken: string,
  month: string,
  signal?: AbortSignal,
): Promise<FinanceOverview> {
  const request: RequestInit = {
    headers: authorizedHeaders(accessToken),
    credentials: "include",
  };
  if (signal !== undefined) request.signal = signal;
  return requestJson<FinanceOverview>(
    `/api/v1/finance/overview?month=${encodeURIComponent(month)}`,
    request,
  );
}

export async function createFinanceCategory(
  accessToken: string,
  idempotencyKey: string,
  command: CategoryCommand,
): Promise<FinanceEvent> {
  return financeCommand(
    "/api/v1/finance/categories",
    accessToken,
    idempotencyKey,
    command,
  );
}

export async function recordFinanceTransaction(
  accessToken: string,
  idempotencyKey: string,
  command: TransactionCommand,
): Promise<FinanceEvent> {
  return financeCommand(
    "/api/v1/finance/transactions",
    accessToken,
    idempotencyKey,
    command,
  );
}

export async function setFinanceBudget(
  accessToken: string,
  idempotencyKey: string,
  command: BudgetCommand,
): Promise<FinanceEvent> {
  return financeCommand(
    "/api/v1/finance/budgets",
    accessToken,
    idempotencyKey,
    command,
  );
}

export async function createFinanceRecurringEntry(
  accessToken: string,
  idempotencyKey: string,
  command: RecurringEntryCommand,
): Promise<FinanceEvent> {
  return financeCommand(
    "/api/v1/finance/recurring",
    accessToken,
    idempotencyKey,
    command,
  );
}

async function financeCommand<T extends object>(
  url: string,
  accessToken: string,
  idempotencyKey: string,
  command: T,
): Promise<FinanceEvent> {
  return requestJson<FinanceEvent>(url, {
    method: "POST",
    headers: {
      ...authorizedHeaders(accessToken),
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey,
    },
    credentials: "include",
    body: JSON.stringify(command),
  });
}

async function requestJson<T>(url: string, request: RequestInit): Promise<T> {
  const response = await fetch(url, request);
  if (!response.ok) throw new Error(await problemMessage(response));
  return (await response.json()) as T;
}

function jsonHeaders(): HeadersInit {
  return { Accept: "application/json", "Content-Type": "application/json" };
}

function authorizedHeaders(accessToken: string): Record<string, string> {
  return { Accept: "application/json", Authorization: `Bearer ${accessToken}` };
}

async function problemMessage(response: Response): Promise<string> {
  try {
    const problem = (await response.json()) as { detail?: unknown };
    if (typeof problem.detail === "string") return problem.detail;
  } catch {
    // A non-JSON proxy failure is summarized by its status below.
  }
  return `ResFinance request failed with ${response.status}`;
}
