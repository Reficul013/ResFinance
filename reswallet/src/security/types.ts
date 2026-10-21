export interface PublicIdentity {
  public_key: string;
  address: string;
}

export interface KdfParameters {
  algorithm: "Argon2id";
  version: 19;
  memory_kib: number;
  iterations: number;
  parallelism: number;
  salt_b64: string;
}

export interface EncryptedSeedRecord {
  version: 1;
  kdf: KdfParameters;
  cipher: {
    algorithm: "AES-256-GCM";
    nonce_b64: string;
    ciphertext_b64: string;
  };
  public_identity: PublicIdentity;
}

export interface VaultStorage {
  load(): Promise<EncryptedSeedRecord | null>;
  save(record: EncryptedSeedRecord): Promise<void>;
  clear(): Promise<void>;
}

export type JsonValue =
  null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };

export interface SignIntentRequest {
  version: 1;
  intent_id: string;
  action:
    "auth.login" | "split.approve" | "credits.fund" | "settlement.authorize";
  resource_id: string;
  parameters: { [key: string]: JsonValue };
  parameters_hash: string;
  nonce: string;
  issued_at: string;
  expires_at: string;
  origin: string;
  audience: "resfinance-api";
  network_id: "pinned-local-network";
}

export interface SignedIntent extends Omit<SignIntentRequest, "parameters"> {
  actor_public_key: string;
  actor_address: string;
  signature: string;
}
