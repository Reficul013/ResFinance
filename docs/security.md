# Security Contract

Status: Milestones 1 and 2 application encryption, wallet hardening, and authentication implemented for local development

## Trust boundaries

1. Web pages are untrusted, including the ResFinance page when compromised by XSS or a dependency.
2. ResWallet is the only boundary allowed to hold an unlocked seed or private key.
3. FastAPI authenticates users, authorizes resources, verifies signed intents, and exposes `/api/v1`.
4. ResContract and ResilientDB are private services reachable only by application services and controlled workers.
5. External data/model providers are untrusted inputs and cannot initiate writes outside their ingestion commands.
6. The local instruction model receives only the authenticated user's structured fact bundle. It selects fact IDs but cannot author unchecked claims or call application tools.

## Wallet invariants

- Seeds, private keys, passwords, password-derived keys, and decrypted key material never enter page messages, network requests, backend services, telemetry, or logs.
- Signing occurs in the extension background security context.
- The page receives only the public key, derived address, signature, signed-intent identifier, and user-approved result.
- Contract-affecting signing requires a human-visible summary and explicit approval.
- Origin, audience, network, expiry, nonce, parameter hash, action, and resource version are bound into the signature.
- The extension defaults to no allowed application origins and uses an explicit allowlist.
- Locked state rejects signing; sensitive in-memory state is cleared on lock, logout, extension suspension, and timeout.

## Key storage

The approved implementation must use Argon2id with documented parameters to derive a key-encryption key from the user password and AES-256-GCM with a fresh nonce for each encrypted seed. Authentication metadata, ciphertext, nonce, salt, and version may be persisted. Passwords, plaintext seeds, plaintext private keys, derived keys, and an exportable encryption key stored beside its ciphertext may not be persisted.

ResFinance application payloads use separate AES-256-GCM data-encryption keys before ResilientDB persistence. Cleartext indexes contain only pseudonymous IDs, record type, schema version, and UTC timestamps. Erasure appends a tombstone and destroys the applicable data-encryption key.

For local development, the Compose certificate initializer generates a 32-byte Finance event key into the existing private Docker certificate volume. The API mounts that file read-only; the key is never committed or written into the container image. This is local non-production key handling and does not lift the deployment hold or replace the deferred production KMS design.

Milestone 1 implements authenticated encryption for event and blob repositories. Event payloads are stored as AES-256-GCM envelopes, and large blobs are compressed, encrypted, content-addressed, chunked, and verified on read. Local acceptance tests use an ephemeral test key; production key custody and destruction remain Milestone 8 work, which is on hold.

## Service controls

- Access tokens are memory-only in the browser.
- Refresh-session hashes, revocation, nonces, and audit events are stored in ResilientDB.
- All writes require authorization and idempotency; contract writes additionally require a verified signed intent.
- ResContract caller addresses are accepted only through the private gateway after verification.
- Contract state is authoritative. Finance changes only after a confirmed receipt.
- Workers use least-privilege identities and singleton leases stored in ResilientDB.
- Smart Savings Insights expose read-only application-service methods only. Prompt text and model output are untrusted; unknown evidence IDs, prompt injection, low confidence, and prohibited actions fail closed to a deterministic template or refusal.

## Logging and evidence

Structured logs use allowlisted fields. The following are always redacted or omitted: authorization headers, cookies, signatures when not required for a receipt reference, signed payload bodies, passwords, seeds, private keys, decrypted payloads, PII, provider credentials, and raw extension messages.

Security tests must inspect the browser page, extension messaging, network capture, server logs, worker logs, error responses, and generated feasibility evidence for prohibited values.

## Current ResWallet disposition

The pinned official ResVault source fails this contract. ADR 0001 therefore created ResWallet as the custom ResFinance wallet while preserving the useful browser-wallet role and explicit approval flow. Milestone 2 implements ResWallet as a Manifest V3 extension with a versioned Argon2id/AES-256-GCM seed record, memory-only unlocked state, exact-origin messaging, extension-owned approvals, and background-only Ed25519 signing. Authentication refresh hashes, nonce use, and revocation markers persist in ResilientDB while access tokens remain memory-only.

Local acceptance and remaining non-production limits are recorded in [`milestone2-wallet-authentication.md`](milestone2-wallet-authentication.md). The original source findings remain in [`audits/resvault-2026-10-12.md`](audits/resvault-2026-10-12.md).
