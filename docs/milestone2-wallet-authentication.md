# Milestone 2 Hardened Wallet and Authentication

Status: Complete for local development

Evidence date: 2026-10-13 America/Los_Angeles

## Delivered boundaries

- A ResVault-compatible Manifest V3 extension under `resvault/`, implemented from the accepted ADR rather than the unsafe upstream storage and signing bridge.
- One versioned encrypted-seed record using Argon2id and AES-256-GCM. The local policy is 64 MiB, three iterations, parallelism one, a 16-byte random salt, a 12-byte random nonce, and a 32-byte derived key.
- Memory-only passwords, derived keys, decrypted seeds, and signing state. The vault locks after five minutes, extension suspension, page logout, explicit lock, or extension restart.
- An exact-origin content bridge restricted to `https://app.resfinance.local` and the checked local Vite origin. It returns only the public key, derived address, approved signed intent, or a public error.
- An extension-owned approval window that displays the action, requesting origin, resource, network, expiry, and material parameters before signing.
- RFC 8785-compatible canonical intent signing with Ed25519 and signatures bound to action, parameters hash, resource, nonce, origin, audience, network, issuance, and expiry.
- FastAPI challenge, session, refresh, and logout endpoints under `/api/v1/auth`.
- Opaque access tokens held only in API and browser memory. The refresh token is stored only as a SHA-256 hash in ResilientDB and delivered as an HttpOnly, SameSite=Strict cookie.
- Append-only ResilientDB challenge-use, nonce-use, refresh-session, rotation, revocation, and authentication audit records.
- A wallet-login screen that uses the generated `/api/v1` client, requests extension approval, keeps the access token in React memory, refreshes through the cookie, and locks ResVault on logout.
- A pinned native ResilientDB KV client in the FastAPI container; no substitute persistence was introduced.

Exact upstream and cryptography revisions are recorded in [`config/milestone2-lock.json`](../config/milestone2-lock.json). The built extension remains a local-development implementation; this evidence does not claim browser-store review, production key custody, cloud support, or production readiness.

## Security acceptance

Automated coverage proves:

- A restarted extension is locked until an explicit unlock.
- Wrong passwords cannot decrypt the seed.
- Signing while locked, without approval, after timeout, or from the wrong origin fails.
- Altered parameters, wrong networks, expired requests, duplicate wallet nonces, altered signatures, used challenges, and rotated refresh-token replay fail.
- The TypeScript extension signature matches the Python RFC 8785/Ed25519 verifier through a shared compatibility vector.
- The built manifest has no `<all_urls>` permission and the page bridge posts only to the exact page origin.
- The content bridge contains no seed, password, private-key, derived-key, mnemonic, or ciphertext field.
- Storage contains one encrypted-seed record plus public metadata; no raw password, seed, access token, refresh token, or login challenge is persisted.

## Real-stack acceptance

The checked runner created and approved a wallet challenge, established a refresh session through ResilientDB, restarted all four replicas and the client proxy, reconstructed the authentication service, and refreshed successfully. It then proved that the old rotated refresh token, the used challenge, and the logged-out session were rejected.

The rebuilt FastAPI container separately passed the live HTTP flow through its pinned native KV client:

- Challenge: `201`
- Session: `201`
- Refresh rotation: `200`
- Rotated-token replay: `401`
- Logout: `204`
- Wrong origin: `403`

The sanitized record is [`config/milestone2-local-attestation.json`](../config/milestone2-local-attestation.json).

## Verification

```bash
.venv/bin/ruff check .
.venv/bin/mypy
.venv/bin/pytest
.venv/bin/python -m scripts.generate_openapi
docker compose config --quiet

cd client
npm ci
npm run generate:api
npm run check
npm run lint
npm run format:check
npm test
npm run build

cd ../resvault
npm ci
npm run check
npm run lint
npm run format:check
npm test
npm run build
npm run security:inspect
```

Real ResilientDB and live API acceptance:

```bash
docker compose --profile tools up -d --build \
  resdb-1 resdb-2 resdb-3 resdb-4 resdb-proxy resdb-tools
.venv/bin/python -m scripts.milestone2.run_auth_acceptance

docker compose --profile app up -d --build api
.venv/bin/python -m scripts.milestone2.run_http_auth_acceptance
```

To load the local extension, build `resvault/`, open the Chromium extensions page, enable developer mode, and load `resvault/dist` as an unpacked extension. Generated `dist/` output is intentionally not committed.
