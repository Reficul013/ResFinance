export interface WalletIdentity {
  public_key: string;
  address: string;
}

export interface WalletStatus {
  exists: boolean;
  unlocked: boolean;
  identity: WalletIdentity | null;
}

export interface SignedIntent {
  version: 1;
  intent_id: string;
  action:
    "auth.login" | "split.approve" | "credits.fund" | "settlement.authorize";
  actor_public_key: string;
  actor_address: string;
  resource_id: string;
  parameters_hash: string;
  nonce: string;
  issued_at: string;
  expires_at: string;
  origin: string;
  audience: "resfinance-api";
  network_id: "pinned-local-network";
  signature: string;
}

export type JsonValue =
  null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };

export interface SignIntentRequest {
  version: 1;
  intent_id: string;
  action:
    "auth.login" | "split.approve" | "credits.fund" | "settlement.authorize";
  resource_id: string;
  parameters: Record<string, JsonValue>;
  parameters_hash: string;
  nonce: string;
  issued_at: string;
  expires_at: string;
  origin: string;
  audience: "resfinance-api";
  network_id: "pinned-local-network";
}

interface VaultResponse<T> {
  source: "reswallet";
  version: 1;
  request_id: string;
  ok: boolean;
  result?: T;
  error?: string;
}

interface VaultStatusNotice {
  source: "reswallet";
  version: 1;
  type: "STATUS_CHANGED";
  status: WalletStatus;
}

export function getWalletStatus(): Promise<WalletStatus> {
  return sendVaultRequest<WalletStatus>("GET_STATUS", {}, 1500);
}

export function getWalletIdentity(): Promise<WalletIdentity | null> {
  return sendVaultRequest<WalletIdentity | null>("GET_IDENTITY", {}, 1500);
}

export function subscribeWalletStatus(
  listener: (status: WalletStatus) => void,
): () => void {
  function receive(event: MessageEvent<unknown>): void {
    if (event.source !== window || event.origin !== window.location.origin)
      return;
    const notice = parseWalletStatusNotice(event.data);
    if (notice !== null) listener(notice.status);
  }
  window.addEventListener("message", receive);
  return () => window.removeEventListener("message", receive);
}

export function parseWalletStatusNotice(
  value: unknown,
): VaultStatusNotice | null {
  if (!isObject(value)) return null;
  if (
    value.source !== "reswallet" ||
    value.version !== 1 ||
    value.type !== "STATUS_CHANGED" ||
    !isWalletStatus(value.status)
  ) {
    return null;
  }
  return value as unknown as VaultStatusNotice;
}

export function signIntent(intent: SignIntentRequest): Promise<SignedIntent> {
  return sendVaultRequest<SignedIntent>(
    "SIGN_INTENT",
    { intent },
    2 * 60 * 1000,
  );
}

export function lockWallet(): Promise<{ locked: boolean }> {
  return sendVaultRequest<{ locked: boolean }>("LOCK", {}, 1500);
}

export async function hashParameters(
  parameters: Record<string, JsonValue>,
): Promise<string> {
  const bytes = new TextEncoder().encode(canonicalJson(parameters));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}

export function formatIntentTimestamp(value: Date): string {
  return value.toISOString().replace(/\.\d{3}Z$/, "Z");
}

function sendVaultRequest<T>(
  type: "GET_STATUS" | "GET_IDENTITY" | "SIGN_INTENT" | "LOCK",
  payload: object,
  timeoutMs: number,
): Promise<T> {
  const requestId = crypto.randomUUID();
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => {
      window.removeEventListener("message", receive);
      reject(
        new Error(
          "ResWallet did not respond. Install or unlock the extension.",
        ),
      );
    }, timeoutMs);
    function receive(event: MessageEvent<unknown>): void {
      if (event.source !== window || event.origin !== window.location.origin)
        return;
      const response = event.data as Partial<VaultResponse<T>>;
      if (
        response.source !== "reswallet" ||
        response.version !== 1 ||
        response.request_id !== requestId
      ) {
        return;
      }
      window.clearTimeout(timer);
      window.removeEventListener("message", receive);
      if (!response.ok) {
        reject(new Error(response.error ?? "ResWallet request failed"));
        return;
      }
      resolve(response.result as T);
    }
    window.addEventListener("message", receive);
    window.postMessage(
      {
        source: "resfinance-page",
        version: 1,
        request_id: requestId,
        type,
        ...payload,
      },
      window.location.origin,
    );
  });
}

function isWalletStatus(value: unknown): value is WalletStatus {
  if (!isObject(value)) return false;
  if (typeof value.exists !== "boolean" || typeof value.unlocked !== "boolean")
    return false;
  if (value.identity === null) return true;
  return (
    isObject(value.identity) &&
    typeof value.identity.public_key === "string" &&
    typeof value.identity.address === "string"
  );
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function canonicalJson(value: JsonValue): string {
  if (value === null || typeof value === "boolean")
    return JSON.stringify(value);
  if (typeof value === "number") {
    if (!Number.isFinite(value))
      throw new Error("Intent parameters must be finite");
    return JSON.stringify(value);
  }
  if (typeof value === "string") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  return `{${Object.keys(value)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key]!)}`)
    .join(",")}}`;
}
