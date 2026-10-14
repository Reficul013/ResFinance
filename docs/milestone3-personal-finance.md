# Milestone 3 Personal Finance Dashboard

Status: Complete for local development

Evidence date: 2026-10-14 America/Los_Angeles

## Delivered boundaries

- One encrypted, append-only `finance-account` event stream per wallet-backed user.
- Income and expense categories with direction validation.
- Integer-cent USD transactions and compensating void events; persisted events are never edited in place.
- Monthly category budgets with exact basis-point utilization and `on_track`, `near_limit`, or `over_budget` alerts.
- Monthly recurring income and expense entries. A linked transaction satisfies a recurring entry for that month so projected savings does not double count it.
- Read-only receivable and payable projections. Only the application-only confirmed-contract method can append obligation events, and every such event requires a source event ID and ResContract receipt.
- A deterministic reducer that rebuilds categories, transactions, budgets, recurring entries, obligations, balances, and savings from the event stream.
- Authenticated `/api/v1/finance` endpoints with generated TypeScript types, RFC 9457 errors, optimistic aggregate versions, and required idempotency keys on writes.
- An accessible `/finance` dashboard with cash-flow chart, text equivalents, budget progress, validation, empty/loading/error states, responsive tables, and record-level provenance.
- React Hook Form and Zod validation, TanStack Query state management, Recharts visualization, React Router navigation, Vitest coverage, and a checked Chromium Playwright journey.

## Versioned savings formula

The Crypto dashboard will consume the Finance-owned formula version `finance-savings-v1`.

```text
actual savings
  = recorded monthly income - recorded monthly expenses

projected savings
  = actual savings
  + unmatched active monthly recurring income
  - unmatched active monthly recurring expenses
  + open receivables due in the month
  - open payables due in the month

available savings = max(0, projected savings)
```

Every response includes the formula version, deterministic calculation ID, projection version, freshness timestamp, and source event IDs. Money remains integer USD cents throughout the backend and API. The browser converts validated decimal text to cents without binary floating-point monetary arithmetic.

## Real-stack acceptance

The checked runner appended two categories, income, an expense, a budget, a recurring expense, a confirmed payable, and a confirmed receivable to the real ResilientDB stack. It proved an idempotent retry, restarted all four replicas and the client proxy, rebuilt the projection from encrypted events, and reproduced the exact result:

- Income: `500000` cents
- Expenses: `90000` cents
- Balance and actual savings: `410000` cents
- Outstanding recurring expense: `150000` cents
- Payable: `20000` cents
- Receivable: `30000` cents
- Projected and available savings: `270000` cents
- Budget utilization: `9000` basis points, `near_limit`
- Projection version: `8`

The sanitized record is [`config/milestone3-local-attestation.json`](../config/milestone3-local-attestation.json).

The rebuilt FastAPI container also passed a live wallet-authenticated Finance flow through its pinned native ResilientDB client: category creation `201`, idempotent duplicate `201`, overview `200`, and invalid access token `401`.

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
npx playwright install chromium
npm run test:e2e
```

Real ResilientDB and live API acceptance:

```bash
docker compose --profile tools up -d --build \
  resdb-1 resdb-2 resdb-3 resdb-4 resdb-proxy resdb-tools
.venv/bin/python -m scripts.milestone3.run_finance_acceptance \
  --output config/milestone3-local-attestation.json

docker compose --profile app up -d --build api
.venv/bin/python -m scripts.milestone3.run_http_finance_acceptance
```

This evidence is local-development acceptance. It does not claim cloud, production, or independent Byzantine fault-domain readiness. Smart Savings Insights remain Milestone 8 read-only AI work, and group creation/settlement remains Milestone 4.
