interface ApprovalDetails {
  request_id: string;
  origin: string;
  action: string;
  resource_id: string;
  parameters: object;
  network_id: string;
  expires_at: string;
}

const requestId = new URL(location.href).searchParams.get("request");
const status = element("status");
const details = element("details");
const approve = element("approve");
let decided = false;

approve.addEventListener("click", () => void decide(true));
element("reject").addEventListener("click", () => void decide(false));

if (requestId === null) {
  status.textContent = "This approval request is invalid.";
} else {
  void load();
}

window.addEventListener("beforeunload", () => {
  if (!decided && requestId !== null) {
    void chrome.runtime.sendMessage({
      type: "APPROVAL_DECISION",
      request_id: requestId,
      approved: false,
    });
  }
});

async function load(): Promise<void> {
  try {
    const value = await request<ApprovalDetails>({
      type: "APPROVAL_DETAILS",
      request_id: requestId,
    });
    text("action", value.action);
    text("origin", value.origin);
    text("resource", value.resource_id);
    text("network", value.network_id);
    text("expires", new Date(value.expires_at).toLocaleString());
    text("parameters", JSON.stringify(value.parameters, null, 2));
    approve.textContent =
      value.action === "auth.login" ? "Approve & Login" : "Approve and sign";
    status.textContent =
      "Confirm that this exact action and its parameters are expected.";
    details.hidden = false;
  } catch (error) {
    status.textContent = safeError(error);
  }
}

async function decide(approved: boolean): Promise<void> {
  if (requestId === null) return;
  try {
    await request({
      type: "APPROVAL_DECISION",
      request_id: requestId,
      approved,
    });
    decided = true;
    window.close();
  } catch (error) {
    status.textContent = safeError(error);
  }
}

async function request<T = unknown>(message: object): Promise<T> {
  const response = (await chrome.runtime.sendMessage(message)) as
    | {
        ok: boolean;
        result?: T;
        error?: string;
      }
    | undefined;
  if (response === undefined)
    throw new Error("ResWallet background is unavailable");
  if (!response.ok)
    throw new Error(response.error ?? "ResWallet request failed");
  return response.result as T;
}

function element(id: string): HTMLElement {
  const value = document.getElementById(id);
  if (value === null) throw new Error(`Missing ResWallet element: ${id}`);
  return value;
}

function text(id: string, value: string): void {
  element(id).textContent = value;
}

function safeError(error: unknown): string {
  return error instanceof Error ? error.message : "ResWallet approval failed";
}
