# Milestone 1 Platform Foundation

Status: Complete for local development

Evidence date: 2026-10-13

## Delivered boundaries

- A strict React 19, TypeScript, and Vite client under `client/src/{app,features,components,lib}`.
- A checked OpenAPI document and generated TypeScript schema. Browser code reaches the backend only through the `/api/v1` client module.
- A FastAPI application factory with a versioned health endpoint and RFC 9457 Problem Details handlers.
- Explicit domain, application, and infrastructure modules. Domain code has no infrastructure imports.
- The exact `BTC | ETH | SOL` asset enum and typed market, on-chain, and sentiment provider ports.
- An append-only event repository with deterministic key families, aggregate-version checks, idempotency conflict detection, prefix-index reads, and projection rebuilds.
- AES-256-GCM payload envelopes with authenticated clear metadata and plaintext payload hashes. Cleartext storage contains only pseudonymous identifiers and event metadata.
- A compressed, encrypted, content-addressed blob repository with 256 KiB logical chunks and per-chunk plus aggregate hash verification.
- Four persistent ResilientDB replica services and one private client proxy on an internal Compose network. ResilientDB publishes no host port.
- Runtime-generated development certificates and private keys stored only in a Docker named volume.
- Python and client lint, type, test, build, generated-artifact, and Compose validation in CI.

## Real-stack acceptance

The checked acceptance runner wrote an encrypted finance event through the private client proxy, submitted the same command twice, restarted all four replicas and the proxy, reloaded the stream, rebuilt the projection, and submitted the command again.

Observed result:

- Event ID: `evt_0ce804b47116e8d6a58d972a3e36171a`
- Projection result: `12500` USD minor units
- Read after restart: pass
- Deduplication before restart: pass
- Deduplication after restart: pass
- Substitute database: none

The sanitized machine-readable record is [`config/milestone1-local-attestation.json`](../config/milestone1-local-attestation.json). This proves local persistence behavior, not cloud or production readiness.

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
```

Real ResilientDB acceptance:

```bash
docker compose --profile tools up -d --build \
  resdb-1 resdb-2 resdb-3 resdb-4 resdb-proxy resdb-tools
.venv/bin/python -m scripts.milestone1.run_repository_acceptance
```

The application data-encryption key used by the acceptance runner is generated in process memory and is never written to Git, logs, or the Docker volume. A persistent local key provider and production KMS design are intentionally outside this milestone; cloud deployment remains on hold.
