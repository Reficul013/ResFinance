import * as ed25519 from "@noble/ed25519";
import { argon2idAsync } from "@noble/hashes/argon2.js";
import { sha512 } from "@noble/hashes/sha2.js";

import {
  base64ToBytes,
  base58Encode,
  bytesToBase64,
  canonicalBytes,
  sha256Hex,
  toArrayBuffer,
} from "./canonical";
import type {
  EncryptedSeedRecord,
  KdfParameters,
  PublicIdentity,
} from "./types";

ed25519.hashes.sha512 = sha512;

export interface Argon2Policy {
  memory_kib: number;
  iterations: number;
  parallelism: number;
}

export const DEFAULT_ARGON2_POLICY: Argon2Policy = {
  memory_kib: 64 * 1024,
  iterations: 3,
  parallelism: 1,
};

export function randomBytes(length: number): Uint8Array {
  return crypto.getRandomValues(new Uint8Array(length));
}

export async function deriveIdentity(
  seed: Uint8Array,
): Promise<PublicIdentity> {
  if (seed.length !== 32)
    throw new Error("ResVault seed must contain exactly 32 bytes");
  const publicKey = ed25519.getPublicKey(seed);
  const digest = new Uint8Array(
    await crypto.subtle.digest("SHA-256", toArrayBuffer(publicKey)),
  );
  const address = `0x${Array.from(digest.slice(-20), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("")}`;
  return { public_key: base58Encode(publicKey), address };
}

export function signBytes(message: Uint8Array, seed: Uint8Array): Uint8Array {
  return ed25519.sign(message, seed);
}

export async function encryptSeed(
  seed: Uint8Array,
  password: string,
  identity: PublicIdentity,
  policy: Argon2Policy = DEFAULT_ARGON2_POLICY,
): Promise<EncryptedSeedRecord> {
  const salt = randomBytes(16);
  const nonce = randomBytes(12);
  const kdf: KdfParameters = {
    algorithm: "Argon2id",
    version: 19,
    memory_kib: policy.memory_kib,
    iterations: policy.iterations,
    parallelism: policy.parallelism,
    salt_b64: bytesToBase64(salt),
  };
  const metadata = { version: 1, kdf, public_identity: identity };
  const keyBytes = await deriveKey(password, kdf);
  try {
    const key = await crypto.subtle.importKey(
      "raw",
      toArrayBuffer(keyBytes),
      "AES-GCM",
      false,
      ["encrypt"],
    );
    const ciphertext = await crypto.subtle.encrypt(
      {
        name: "AES-GCM",
        iv: toArrayBuffer(nonce),
        additionalData: toArrayBuffer(canonicalBytes(metadata)),
      },
      key,
      toArrayBuffer(seed),
    );
    return {
      version: 1,
      kdf,
      cipher: {
        algorithm: "AES-256-GCM",
        nonce_b64: bytesToBase64(nonce),
        ciphertext_b64: bytesToBase64(new Uint8Array(ciphertext)),
      },
      public_identity: identity,
    };
  } finally {
    keyBytes.fill(0);
  }
}

export async function decryptSeed(
  record: EncryptedSeedRecord,
  password: string,
): Promise<Uint8Array> {
  if (
    record.version !== 1 ||
    record.kdf.algorithm !== "Argon2id" ||
    record.kdf.version !== 19 ||
    record.cipher.algorithm !== "AES-256-GCM"
  ) {
    throw new Error("ResVault encrypted-seed format is not supported");
  }
  const metadata = {
    version: record.version,
    kdf: record.kdf,
    public_identity: record.public_identity,
  };
  const keyBytes = await deriveKey(password, record.kdf);
  try {
    const key = await crypto.subtle.importKey(
      "raw",
      toArrayBuffer(keyBytes),
      "AES-GCM",
      false,
      ["decrypt"],
    );
    const plaintext = await crypto.subtle.decrypt(
      {
        name: "AES-GCM",
        iv: toArrayBuffer(base64ToBytes(record.cipher.nonce_b64)),
        additionalData: toArrayBuffer(canonicalBytes(metadata)),
      },
      key,
      toArrayBuffer(base64ToBytes(record.cipher.ciphertext_b64)),
    );
    const seed = new Uint8Array(plaintext);
    if (seed.length !== 32)
      throw new Error("decrypted ResVault seed is invalid");
    return seed;
  } catch {
    throw new Error("password or encrypted ResVault seed is invalid");
  } finally {
    keyBytes.fill(0);
  }
}

export async function hashParameters(
  value: Record<string, unknown>,
): Promise<string> {
  return sha256Hex(value);
}

async function deriveKey(
  password: string,
  parameters: KdfParameters,
): Promise<Uint8Array> {
  if (password.length < 12)
    throw new Error("ResVault password must be at least 12 characters");
  const passwordBytes = new TextEncoder().encode(password);
  try {
    return await argon2idAsync(
      passwordBytes,
      base64ToBytes(parameters.salt_b64),
      {
        t: parameters.iterations,
        m: parameters.memory_kib,
        p: parameters.parallelism,
        version: parameters.version,
        dkLen: 32,
        maxmem: parameters.memory_kib * 1024 + 8 * 1024,
        asyncTick: 10,
      },
    );
  } finally {
    passwordBytes.fill(0);
  }
}
