# REST API Contract

Status: Milestone 2 authentication boundary implemented; later feature endpoints remain milestone-ordered

## Boundary

The browser calls application services only through generated clients for `/api/v1`. ResilientDB, ResContract GraphQL, contract CLI endpoints, and provider credentials are private infrastructure and are never browser-accessible.

All requests and responses use JSON unless an endpoint explicitly documents another representation. Timestamps are RFC 3339 UTC values. Unknown fields are rejected on commands. Public identifiers are opaque strings.

## Shared types

```text
CryptoAsset = "BTC" | "ETH" | "SOL"
Money = { "currency": "USD", "minor_units": int64 }
DecimalString = /^-?(0|[1-9][0-9]*)(\.[0-9]+)?$/
```

Money never uses a JSON floating-point number. Crypto quantities, prices, returns, weights, and probabilities use validated decimal strings with endpoint-specific scale and bounds.

## Commands and idempotency

Every state-changing endpoint requires `Idempotency-Key`. The value is scoped to the authenticated tenant and command type. Reusing a key with the same canonical request returns the original outcome; reusing it with a different request returns `409 Conflict`.

Successful command responses expose:

```json
{
  "event_id": "opaque-event-id",
  "projection_version": 12,
  "occurred_at_utc": "2026-10-12T00:00:00Z",
  "receipt_ids": []
}
```

Contract-affecting commands additionally require a backend-verified signed intent. A finance event may be appended only after confirmed ResContract state and a receipt.

## Signed intent

The signed bytes are RFC 8785 canonical JSON of every field except `signature`:

```json
{
  "version": 1,
  "intent_id": "opaque-id",
  "action": "settlement.authorize",
  "actor_public_key": "base58-ed25519-public-key",
  "actor_address": "derived-address",
  "resource_id": "opaque-resource-id",
  "parameters_hash": "sha256-hex",
  "nonce": "single-use-value",
  "issued_at": "2026-10-12T00:00:00Z",
  "expires_at": "2026-10-12T00:05:00Z",
  "origin": "https://app.resfinance.local",
  "audience": "resfinance-api",
  "network_id": "pinned-local-network",
  "signature": "base58-ed25519-signature"
}
```

The backend verifies the signature, public-key/address relationship, action, audience, network, origin policy, expiry, nonce uniqueness, parameter hash, authorization, and expected resource version before invoking ResContract.

`origin` is a required signed-intent field. It must exactly equal the browser `Origin` header and an explicitly configured ResFinance origin.

## Authentication

- `POST /api/v1/auth/challenges` accepts a public Ed25519 identity and returns a five-minute challenge.
- `POST /api/v1/auth/sessions` consumes an approved `auth.login` signed intent and the matching challenge.
- `POST /api/v1/auth/refresh` rotates the refresh session and returns a new memory-only access token.
- `DELETE /api/v1/auth/sessions/current` revokes the session and expires the refresh cookie.

Access tokens are opaque and held only in API/browser process memory. Refresh tokens use an HttpOnly, SameSite=Strict cookie; only their SHA-256 hashes are persisted in ResilientDB. Challenges are also persisted only as hashes. Challenge use, intent nonces, refresh rotation, and logout append durable use or revocation markers. The checked local environment permits `https://app.resfinance.local` and `http://127.0.0.1:5173` exactly.

## Errors

Errors use RFC 9457 Problem Details with `application/problem+json`:

```json
{
  "type": "https://resfinance.local/problems/idempotency-conflict",
  "title": "Idempotency key conflict",
  "status": 409,
  "detail": "The key was previously used for a different command.",
  "instance": "/api/v1/groups/example/settlements",
  "trace_id": "opaque-trace-id"
}
```

Validation errors may add an `errors` array containing field paths and stable machine-readable codes. Problem details never echo secrets, raw signed payloads, decrypted records, or provider credentials.

## Concurrency, paging, and provenance

- Commands that depend on aggregate state include the expected version; stale commands return `409`.
- Collection endpoints use opaque cursors and deterministic ordering, never an unbounded “list everything” operation.
- Responses include projection freshness and the source event IDs used to build the view.
- Market, forecast, research, and AI responses include source IDs, observation/as-of times, retrieval times, model/dataset hashes, and applicable warnings.
- Scenario endpoints are read-only and cannot update Finance or the saved default amount.
