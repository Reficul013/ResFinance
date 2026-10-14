# ResFinance

ResFinance is a planned wallet-authenticated finance platform that connects personal budgeting, shared expenses, and explainable BTC/ETH/SOL portfolio analysis through one auditable financial record.

> **Project status:** Milestones 0–6 are complete for local, non-commercial development and research. The feasibility gates, encrypted ResilientDB platform foundation, hardened ResVault-compatible extension, wallet authentication, Personal Finance dashboard, Groups contractual-settlement workflow, crypto ingestion/feature store, and reproducible ML research mechanics pass. The deterministic Milestone 6 smoke candidate was not promoted because it did not beat the declared naive-baseline MAE criterion. Milestone 7 risk, portfolio, and Crypto dashboard work is next. Cloud and production deployment remain on hold.

## What the product will do

Most finance products separate budgeting, bill splitting, and investing. ResFinance is designed to connect them into one continuous user journey:

```text
Earn → Spend → Split → Settle → Update Finance → Calculate Savings → Explore BTC/ETH/SOL → Forecast → Assess Risk → Build Portfolio
```

A user will be able to connect a ResVault wallet, manage personal finances, split expenses with friends, approve settlements, and use the resulting savings calculation as the default amount for a risk-aware crypto portfolio analysis.

## The three product areas

### Personal Finance

- Record income, expenses, categories, budgets, and recurring items.
- Track receivables and payables created by shared expenses.
- View cash-flow summaries, budget alerts, and actual or projected monthly savings.
- Receive practical, evidence-linked Smart Savings Insights.
- Preserve an auditable history instead of silently overwriting financial records.

### Friends & Groups

- Create groups and shared expenses with equal or custom splits.
- Ask each participant to approve or reject their obligation with ResVault.
- Track who owes whom and whether an obligation is pending, open, partially settled, settled, rejected, or cancelled.
- Settle with internal, non-redeemable credits and receive immutable receipts.
- Reflect confirmed obligations and settlements back into Personal Finance.

### Crypto Investments

- Explore market, sentiment, and on-chain signals for **BTC, ETH, and SOL only**.
- Review forecasts with expected return, upside probability, uncertainty intervals, freshness, and provenance.
- Complete a risk questionnaire and receive an explainable long-only portfolio allocation.
- Start with the savings amount calculated by Personal Finance.
- Use **Analyze Another Amount** for a separate what-if scenario without changing financial records.

## Example user journey

1. Alex connects ResVault, which becomes the wallet-backed signing identity.
2. Alex records income, expenses, budgets, and recurring costs.
3. Alex pays a group expense and creates a split among friends.
4. Participants explicitly approve their shares, and the contract records the obligations.
5. Confirmed settlements update group balances and Alex's Personal Finance view.
6. ResFinance calculates Alex's available savings and suggests realistic improvements.
7. Alex reviews BTC, ETH, and SOL signals and research-backed forecasts.
8. A risk profile and optimizer convert the selected amount into an explainable portfolio.
9. Alex can test another amount without modifying the original savings record.

## How the platform is designed

| Component | Role |
|---|---|
| React, TypeScript, and Vite | Shared user interface for Finance, Groups, and Crypto Investments |
| FastAPI REST API | Authentication, validation, business rules, orchestration, and `/api/v1` endpoints |
| Apache ResilientDB | The only persistent store for application events, market data, forecasts, model artifacts, and research records |
| ResVault | Wallet identity, local key custody, challenge signing, and explicit approval of contract-affecting actions |
| ResContract | Authoritative obligation, settlement-credit, and receipt state transitions |
| Ingestion and ML workers | Market-data collection, reproducible research runs, forecasts, and model evaluation |
| Read-only AI assistant | Evidence-linked explanations of budgets, obligations, forecasts, uncertainty, and allocations |

The application follows an append-only event model. Projections can be rebuilt, writes are idempotent, sensitive payloads are encrypted before persistence, and every meaningful result carries freshness and provenance information.

## Forecasting and portfolio research

The forecasting implementation is a documented clean-room three-asset adaptation of MSPCIFormer. ResFinance combines market, sentiment, and on-chain inputs using masked Adaptive Multi-Source Gating and evaluates the approach against naive/zero-return, linear, LSTM, market-only, fixed-fusion, and every one-source-removed baseline.

Research runs use five chronological expanding walk-forward folds with a 15-day embargo, validation-only split-conformal intervals, deterministic CPU execution, immutable manifests, encrypted content-addressed artifacts, and complete data/code/model provenance. Only a model that passes explicit evaluation criteria may be promoted through an immutable event. Forecasts will feed the Milestone 7 constrained BTC/ETH/SOL portfolio optimizer.

## Important product boundaries

- ResFinance does not transfer fiat, native cryptocurrency, or tokens.
- Internal settlement credits are non-redeemable and have no claimed monetary value.
- The platform does not execute trades, hold exchange assets, or provide custody.
- Portfolio outputs are analytical scenarios, not guaranteed returns or financial advice.
- The AI assistant is read-only: it cannot modify records, sign actions, settle obligations, or trade.
- ResVault private keys and seeds must never leave the extension.
- Apache ResilientDB is the sole persistent application and research database.

## Current development status

Milestone 0 is complete for the declared local, non-commercial research scope. The repository pins ResilientDB, ResContract, ResVault, the toolchain, and the initial local models; defines the REST, security, and research contracts; and provides a reproducible feasibility harness. A source-pinned, labeled ARM64 image and documented compatibility patch passed four-replica persistence/failure tests, a real 100 MiB round trip, persistent ResContract lifecycle tests, and the signed REST-to-contract-to-event slice. The official ResVault implementation failed its audit, while the disposable M0 signer proved the approval and non-disclosure boundary; Milestone 2 subsequently delivered the persistent hardened extension.

Coin Metrics daily prices cover BTC/ETH/SOL, while daily active-address and transaction counts cover BTC/ETH for the full fixed research period. DefiLlama SOL TVL and stablecoin-supply proxies reach the research boundary with their earlier and internal gaps explicitly masked. Bounded GDELT daily aggregates cover sentiment and were hash-verified through real ResilientDB. Provider terms are recorded for the declared research-only scope. See the [Milestone 0 feasibility status](docs/feasibility.md) and [provider terms review](docs/provider-terms-review.md).

Cloud and production deployment are intentionally deferred. Completing the local application will not imply cloud support or production readiness; deployment requires a separate ResilientDB cloud feasibility review and approved architecture decision record.

Milestone 1 adds the strict React/Vite and FastAPI foundations, checked OpenAPI-generated client types, RFC 9457 errors, typed provider ports, AES-256-GCM event/blob repositories, idempotency and projection rebuilds, and a four-replica private Compose topology with a separate ResilientDB client proxy. The real-stack acceptance test passed encrypted write, full restart, readback, rebuild, and deduplication without another database. See the [Milestone 1 platform foundation](docs/milestone1-platform-foundation.md).

Milestone 2 adds the hardened Manifest V3 ResVault-compatible extension, Argon2id/AES-256-GCM encrypted seed custody, exact-origin approval/signing, challenge login, memory-only access tokens, ResilientDB refresh-session hashes, rotation, replay defense, and logout revocation. The authentication state survived a full four-replica restart, and the rebuilt live FastAPI container passed the complete HTTP flow through its pinned native ResilientDB client. See the [Milestone 2 wallet and authentication evidence](docs/milestone2-wallet-authentication.md).

Milestone 3 adds the authenticated Personal Finance dashboard and encrypted append-only finance domain: categories, income and expenses, compensating voids, monthly budgets and alerts, recurring entries, read-only contract-backed receivable/payable projections, exact integer-cent summaries, and the versioned `finance-savings-v1` calculation. The projection rebuilt identically after a full four-replica restart, the live FastAPI container passed authenticated native-ResilientDB writes and reads, and Chromium Playwright reproduced balances, budget alerts, savings, and provenance. See the [Milestone 3 Personal Finance evidence](docs/milestone3-personal-finance.md).

Milestone 4 adds authenticated Groups, exact shared-expense splits, ResVault-signed participant decisions, obligation notifications, a deployed `ResFinanceSettlement.sol` state machine, non-redeemable internal credits, partial/full settlement, immutable receipts, and confirmed Finance propagation. A real-stack run recovered exactly one missing confirmation after an injected post-contract crash and a restart of every ResilientDB and ResContract process; Group and Finance balances then matched exactly. See the [Milestone 4 Groups and contractual settlement evidence](docs/milestone4-groups-settlement.md).

Milestone 5 adds Coin Metrics market and BTC/ETH on-chain adapters, CoinGecko current-quote fallback, DefiLlama SOL proxy ingestion with explicit missing observations, and a bounded GDELT aggregate CSV adapter. Immutable observations, provider revisions, availability times, retrieval times, response checksums, license dispositions, ingestion attempts, point-in-time features, masks, and dataset manifests persist only in ResilientDB. Live provider smoke checks passed, and the real-stack acceptance proved repeat-ingestion and feature idempotency, provider-failure isolation, no-lookahead selection, SOL masks, and rejection of a fourth asset. See the [Milestone 5 crypto ingestion and feature store evidence](docs/milestone5-crypto-ingestion-feature-store.md).

Milestone 6 adds deterministic smoke-data generation; naive, linear, and LSTM baselines; the clean-room three-asset MSPCIFormer adaptation; masked Adaptive Multi-Source Gating; market-only, fixed-fusion, and source-removal ablations; five expanding walk-forward folds; validation-only conformal intervals; full statistical and portfolio-relevant metrics; deterministic checkpoints and plots; immutable model-promotion rules; and encrypted artifact persistence in ResilientDB. Two CPU smoke runs produced identical dataset and prediction hashes, and all 39 artifacts were restored byte-for-byte from the real four-replica stack. The adaptive smoke candidate was correctly rejected by the declared MAE gate, so no model-performance or statistical-significance claim is made. See the [Milestone 6 reproducible ML research evidence](docs/milestone6-reproducible-ml-research.md).

## Local verification

```bash
.venv/bin/python -m pip install \
  -r requirements-dev.txt -r requirements-milestone0.txt \
  -r requirements-api.txt -r requirements-ml.txt
.venv/bin/ruff check .
.venv/bin/mypy
.venv/bin/pytest

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

cd ../resvault
npm ci
npm run check
npm run lint
npm run format:check
npm test
npm run build
npm run security:inspect
```

The real ResilientDB repository acceptance requires the source-pinned local image built during Milestone 0:

```bash
docker compose --profile tools up -d --build \
  resdb-1 resdb-2 resdb-3 resdb-4 resdb-proxy resdb-tools
.venv/bin/python -m scripts.milestone1.run_repository_acceptance

.venv/bin/python -m scripts.milestone2.run_auth_acceptance
docker compose --profile app up -d --build api
.venv/bin/python -m scripts.milestone2.run_http_auth_acceptance

.venv/bin/python -m scripts.milestone3.run_finance_acceptance \
  --output config/milestone3-local-attestation.json
.venv/bin/python -m scripts.milestone3.run_http_finance_acceptance

docker compose --profile tools up -d --build --wait \
  resdb-tools rescontract-tools
.venv/bin/python -m scripts.milestone4.run_groups_acceptance \
  --docker "$(command -v docker)" --restart

.venv/bin/python -m scripts.milestone5.run_crypto_ingestion_acceptance \
  --docker "$(command -v docker)" \
  --output config/milestone5-local-attestation.json

.venv/bin/python -m scripts.milestone6.run_ml_acceptance \
  --docker "$(command -v docker)" \
  --output config/milestone6-local-attestation.json
```

## Repository layout

```text
client/       React and TypeScript application
resvault/     Hardened ResVault-compatible browser extension
server/       FastAPI API, domain services, adapters, and workers
blockchain/   ResContract contracts, gateway adapter, wallet work, and tests
ml/           Data, features, forecasting, evaluation, and portfolio optimization
tests/        Cross-module contract, integration, and end-to-end tests
docs/         Product, architecture, delivery, and development references
```

## Documentation

- [Product specification](docs/project-spec.md)
- [Architecture and implementation plan](docs/architecture-implementation-plan.md)
- [Milestone 0 feasibility status](docs/feasibility.md)
- [Milestone 1 platform foundation](docs/milestone1-platform-foundation.md)
- [Milestone 2 wallet and authentication](docs/milestone2-wallet-authentication.md)
- [Milestone 3 Personal Finance dashboard](docs/milestone3-personal-finance.md)
- [Milestone 4 Groups and contractual settlement](docs/milestone4-groups-settlement.md)
- [Milestone 5 crypto ingestion and feature store](docs/milestone5-crypto-ingestion-feature-store.md)
- [Milestone 6 reproducible ML research](docs/milestone6-reproducible-ml-research.md)
- [REST API contract](docs/rest-api-contract.md)
- [Security contract](docs/security.md)
- [Research protocol](docs/research-protocol.md)
- [Provider coverage and terms review](docs/provider-terms-review.md)
- [ResVault pinned-source audit](docs/audits/resvault-2026-10-12.md)
- [ResilientDB ecosystem development references](docs/development-references.md)
- [Repository instructions for coding agents](AGENTS.md)

## License

See [LICENSE](LICENSE) for the repository license.
