interface StatusResult {
  exists: boolean;
  unlocked: boolean;
  identity: { public_key: string; address: string } | null;
}

const status = element("status");
const setup = element("setup");
const locked = element("locked");
const unlocked = element("unlocked");
const address = element("address");

element("create").addEventListener("click", () => void create(false));
element("import").addEventListener("click", () => void create(true));
element("unlock").addEventListener("click", () => void unlock());
element("lock").addEventListener("click", () => void lock());

void refresh();

async function refresh(): Promise<void> {
  try {
    const current = await request<StatusResult>({ type: "GET_STATUS" });
    setup.hidden = current.exists;
    locked.hidden = !current.exists || current.unlocked;
    unlocked.hidden = !current.unlocked;
    address.textContent = current.identity?.address ?? "";
    status.textContent = !current.exists
      ? "No encrypted seed is stored."
      : current.unlocked
        ? "Unlocked. Signing still requires explicit approval."
        : "Locked. Public identity remains available to ResFinance.";
  } catch (error) {
    status.textContent = safeError(error);
  }
}

async function create(importing: boolean): Promise<void> {
  const password = input("setup-password").value;
  const seed = input("seed").value.trim();
  status.textContent = "Deriving the Argon2id encryption key…";
  try {
    await request({
      type: importing ? "IMPORT" : "CREATE",
      password,
      ...(importing ? { seed_hex: seed } : {}),
    });
    input("setup-password").value = "";
    input("seed").value = "";
    await refresh();
  } catch (error) {
    status.textContent = safeError(error);
  }
}

async function unlock(): Promise<void> {
  status.textContent = "Unlocking encrypted seed…";
  try {
    await request({ type: "UNLOCK", password: input("unlock-password").value });
    input("unlock-password").value = "";
    await refresh();
  } catch (error) {
    status.textContent = safeError(error);
  }
}

async function lock(): Promise<void> {
  await request({ type: "LOCK" });
  await refresh();
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
    throw new Error("ResVault background is unavailable");
  if (!response.ok)
    throw new Error(response.error ?? "ResVault request failed");
  return response.result as T;
}

function element(id: string): HTMLElement {
  const value = document.getElementById(id);
  if (value === null) throw new Error(`Missing ResVault element: ${id}`);
  return value;
}

function input(id: string): HTMLInputElement {
  return element(id) as HTMLInputElement;
}

function safeError(error: unknown): string {
  return error instanceof Error ? error.message : "ResVault request failed";
}
