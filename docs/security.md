# Security Contract

Status: Milestone 0 baseline

## Trust boundaries

1. Web pages are untrusted, including the ResFinance page when compromised by XSS or a dependency.
2. ResVault is the only boundary allowed to hold an unlocked seed or private key.
3. FastAPI authenticates users, authorizes resources, verifies signed intents, and exposes `/api/v1`.
4. ResContract and ResilientDB are private services reachable only by application services and controlled workers.
5. External data/model providers are untrusted inputs and cannot initiate writes outside their ingestion commands.

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

## Service controls

- Access tokens are memory-only in the browser.
- Refresh-session hashes, revocation, nonces, and audit events are stored in ResilientDB.
- All writes require authorization and idempotency; contract writes additionally require a verified signed intent.
- ResContract caller addresses are accepted only through the private gateway after verification.
- Contract state is authoritative. Finance changes only after a confirmed receipt.
- Workers use least-privilege identities and singleton leases stored in ResilientDB.

## Logging and evidence

Structured logs use allowlisted fields. The following are always redacted or omitted: authorization headers, cookies, signatures when not required for a receipt reference, signed payload bodies, passwords, seeds, private keys, decrypted payloads, PII, provider credentials, and raw extension messages.

Security tests must inspect the browser page, extension messaging, network capture, server logs, worker logs, error responses, and generated feasibility evidence for prohibited values.

## Current ResVault disposition

The pinned official ResVault source fails this contract. The accepted path is substantial hardening while preserving ResVault behavior. Details and source evidence are recorded in [`audits/resvault-2026-10-12.md`](audits/resvault-2026-10-12.md) and ADR 0001.
