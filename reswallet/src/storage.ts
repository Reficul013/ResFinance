import type { EncryptedSeedRecord, VaultStorage } from "./security/types";

const STORAGE_KEY = "reswallet.v1.encrypted_seed";

export class ChromeVaultStorage implements VaultStorage {
  async load(): Promise<EncryptedSeedRecord | null> {
    const result = await chrome.storage.local.get(STORAGE_KEY);
    return (result[STORAGE_KEY] as EncryptedSeedRecord | undefined) ?? null;
  }

  async save(record: EncryptedSeedRecord): Promise<void> {
    await chrome.storage.local.set({ [STORAGE_KEY]: record });
  }

  async clear(): Promise<void> {
    await chrome.storage.local.remove(STORAGE_KEY);
  }
}
