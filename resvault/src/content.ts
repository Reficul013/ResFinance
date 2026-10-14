const pageSource = "resfinance-page";
const vaultSource = "resvault";
const port = chrome.runtime.connect({ name: "resfinance-page" });

window.addEventListener("message", (event: MessageEvent<unknown>) => {
  if (event.source !== window || event.origin !== window.location.origin)
    return;
  const message = event.data;
  if (
    !isObject(message) ||
    message.source !== pageSource ||
    message.version !== 1
  )
    return;
  if (
    message.type !== "GET_IDENTITY" &&
    message.type !== "SIGN_INTENT" &&
    message.type !== "LOCK"
  ) {
    return;
  }
  port.postMessage(message);
});

port.onMessage.addListener((message: unknown) => {
  if (
    !isObject(message) ||
    message.source !== vaultSource ||
    message.version !== 1
  )
    return;
  window.postMessage(message, window.location.origin);
});

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
