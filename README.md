# ResFinance

ResFinance is a locally implemented wallet-authenticated finance platform that
connects personal budgeting, shared expenses, and explainable BTC/ETH/SOL
portfolio analysis through one auditable financial record.

For milestone progress and current readiness, see
[`ResFinance-Current-Status.md`](ResFinance-Current-Status.md). The canonical
eight-milestone convention is defined in
[`docs/milestones.md`](docs/milestones.md).

## Product journey

```text
Earn → Spend → Split → Settle → Update Finance → Calculate Savings → Explore BTC/ETH/SOL → Forecast → Assess Risk → Build Portfolio
```

A user connects ResWallet, manages personal finances, splits expenses with
friends, approves contractual settlements, and uses the resulting savings as
the default amount for a risk-aware crypto portfolio analysis.

## Product areas

### Personal Finance

- Record income, expenses, budgets, and recurring items with a fixed,
  direction-aware category catalog.
- Track contract-confirmed receivables and payables from shared expenses.
- View cash-flow summaries, budget alerts, and actual or projected savings.
- Receive practical, evidence-linked Smart Savings Insights.
- Preserve append-only audit history through compensating corrections.

### Friends & Groups

- Create groups and equal or custom shared-expense splits.
- Require each participant to approve or reject obligations with ResWallet.
- Settle with internal, non-redeemable credits and immutable receipts.
- Reflect confirmed obligations and settlements back into Personal Finance.

### Crypto Investments

- Analyze **BTC, ETH, and SOL only** using point-in-time market, sentiment, and
  on-chain data.
- Review eligible forecasts with uncertainty, freshness, and provenance.
- Complete a risk questionnaire and receive an explainable long-only portfolio.
- Reconcile integer-cent allocations exactly to Finance savings or a separate
  non-mutating scenario amount.

## Architecture

| Component | Role |
|---|---|
| React, TypeScript, and Vite | Shared interface for Finance, Groups, and Crypto |
| FastAPI REST API | Authentication, validation, business rules, orchestration, and `/api/v1` |
| Apache ResilientDB | Only persistent store for application events, research data, forecasts, and artifacts |
| ResWallet | Extension-held identity, local key custody, login signing, and explicit action approval |
| ResContract | Authoritative obligation, settlement-credit, and receipt transitions |
| Ingestion and ML workers | Provider collection, reproducible research, forecasts, and evaluation |
| Read-only AI | Evidence-linked explanations without write, wallet, settlement, or trading authority |

The application uses append-only, schema-versioned events; deterministic and
idempotent writes; encrypted sensitive payloads; rebuildable projections; and
freshness/provenance records for meaningful outputs. Browser code reaches
application services only through the generated `/api/v1` REST client.

## Product boundaries

- Apache ResilientDB is the sole persistent application and research database.
- USD is the only V1 fiat denomination; money uses integer cents.
- Crypto support is exactly `BTC | ETH | SOL`.
- ResWallet seeds and private keys never leave the extension.
- ResContract is authoritative for obligations and settlement state.
- Internal settlement credits are non-redeemable and non-monetary.
- ResFinance does not transfer fiat or native cryptocurrency, execute trades,
  provide exchange custody, guarantee returns, or provide investment advice.
- Scenario analysis and AI are read-only and cannot mutate Finance or invoke
  wallet, settlement, or trading operations.
- Cloud and production deployment remain on hold.

## Local verification

Install the pinned dependency sets, then run the repository checks:

```bash
.venv/bin/python -m pip install \
  -r requirements/requirements-dev.txt \
  -r requirements/requirements-milestone0.txt \
  -r requirements/requirements-api.txt \
  -r requirements/requirements-ml.txt \
  -r requirements/requirements-portfolio.txt \
  -r requirements/requirements-ai.txt
.venv/bin/ruff check .
.venv/bin/mypy
.venv/bin/pytest

(cd client && npm ci && npm run generate:api && npm run check && npm run lint && npm run format:check && npm test && npm run build)
(cd reswallet && npm ci && npm run check && npm run lint && npm run format:check && npm test && npm run build && npm run security:inspect)
```

The historical milestone numbers in executable paths are stable compatibility
identifiers. For the complete real-stack command sequence, use the
[`Milestone 7 local operator guide`](docs/milestone9-local-operator-guide.md).

## Repository layout

```text
client/        React and TypeScript application
reswallet/     ResWallet browser extension
server/        FastAPI API, domain services, adapters, and workers
blockchain/    ResContract contracts, gateway adapter, wallet work, and tests
ml/            Data, features, forecasting, evaluation, and portfolio optimization
requirements/  Pinned Python dependency sets for development and runtime areas
tests/         Contract, integration, and end-to-end tests
docs/          Product, architecture, milestone evidence, and development references
```

## Documentation

- [Current milestone status](ResFinance-Current-Status.md)
- [Canonical milestone convention](docs/milestones.md)
- [Product specification](docs/project-spec.md)
- [Architecture and implementation plan](docs/architecture-implementation-plan.md)
- [Local demo runbook](docs/local-demo-runbook.md)
- [REST API contract](docs/rest-api-contract.md)
- [Security contract](docs/security.md)
- [Research protocol](docs/research-protocol.md)
- [Provider coverage and terms review](docs/provider-terms-review.md)
- [ResilientDB ecosystem development references](docs/development-references.md)
- [Repository instructions for coding agents](AGENTS.md)

## License

See [LICENSE](LICENSE) for the repository license.
