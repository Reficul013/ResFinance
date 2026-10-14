export interface WalletIdentity {
  public_key: string;
  address: string;
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
  source: "resvault";
  version: 1;
  request_id: string;
  ok: boolean;
  result?: T;
  error?: string;
}

export function getWalletIdentity(): Promise<WalletIdentity | null> {
  return sendVaultRequest<WalletIdentity | null>("GET_IDENTITY", {}, 1500);
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

function sendVaultRequest<T>(
  type: "GET_IDENTITY" | "SIGN_INTENT" | "LOCK",
  payload: object,
  timeoutMs: number,
): Promise<T> {
  const requestId = crypto.randomUUID();
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => {
      window.removeEventListener("message", receive);
      reject(
        new Error("ResVault did not respond. Install or unlock the extension."),
      );
    }, timeoutMs);
    function receive(event: MessageEvent<unknown>): void {
      if (event.source !== window || event.origin !== window.location.origin)
        return;
      const response = event.data as Partial<VaultResponse<T>>;
      if (
        response.source !== "resvault" ||
        response.version !== 1 ||
        response.request_id !== requestId
      ) {
        return;
      }
      window.clearTimeout(timer);
      window.removeEventListener("message", receive);
      if (!response.ok) {
        reject(new Error(response.error ?? "ResVault request failed"));
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
