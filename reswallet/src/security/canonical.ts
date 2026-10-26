const encoder = new TextEncoder();

export function canonicalJson(value: unknown): string {
  if (
    value === null ||
    typeof value === "boolean" ||
    typeof value === "string"
  ) {
    return JSON.stringify(value);
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      throw new TypeError("canonical JSON cannot contain non-finite numbers");
    }
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => canonicalJson(item)).join(",")}]`;
  }
  if (typeof value !== "object")
    throw new TypeError("canonical JSON value is invalid");
  const object = value as Record<string, unknown>;
  const entries = Object.keys(object)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${canonicalJson(object[key])}`);
  return `{${entries.join(",")}}`;
}

export function canonicalBytes(value: unknown): Uint8Array {
  return encoder.encode(canonicalJson(value));
}

export async function sha256Hex(value: unknown | Uint8Array): Promise<string> {
  const input = value instanceof Uint8Array ? value : canonicalBytes(value);
  const digest = await crypto.subtle.digest("SHA-256", toArrayBuffer(input));
  return Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}

export function toArrayBuffer(value: Uint8Array): ArrayBuffer {
  return Uint8Array.from(value).buffer;
}

export function bytesToBase64(value: Uint8Array): string {
  let binary = "";
  for (const byte of value) binary += String.fromCharCode(byte);
  return btoa(binary);
}

export function base64ToBytes(value: string): Uint8Array {
  const binary = atob(value);
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

const BASE58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";

export function base58Encode(value: Uint8Array): string {
  let leadingZeros = 0;
  while (leadingZeros < value.length && value[leadingZeros] === 0)
    leadingZeros += 1;
  let number = 0n;
  for (const byte of value) number = number * 256n + BigInt(byte);
  let encoded = "";
  while (number > 0n) {
    const remainder = Number(number % 58n);
    number /= 58n;
    encoded = BASE58[remainder]! + encoded;
  }
  return "1".repeat(leadingZeros) + encoded;
}
