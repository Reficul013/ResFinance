# ResFinance

ResFinance is a planned wallet-authenticated finance platform that connects personal budgeting, shared expenses, and explainable BTC/ETH/SOL portfolio analysis through one auditable financial record.

> **Project status:** Milestone 0 feasibility work is in progress. The architecture contracts, version pins, gate harness, and initial upstream audit are implemented, but mandatory real-stack gates have not all passed. Cloud and production deployment remain on hold.

## What the product will do

Most finance products separate budgeting, bill splitting, and investing. ResFinance is designed to connect them into one continuous user journey:

```text
Earn → Spend → Split → Settle → Update Finance → Calculate Savings
     → Explore BTC/ETH/SOL → Forecast → Assess Risk → Build Portfolio
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

The forecasting work is a documented three-asset adaptation of MSPCIFormer. ResFinance will combine market, sentiment, and on-chain inputs using Adaptive Multi-Source Gating and evaluate the approach against naive, linear, sequence-model, market-only, fixed-fusion, and source-removal baselines.

Research runs will use chronological walk-forward evaluation, calibrated forecast intervals, deterministic seeds, immutable manifests, and complete data/code/model provenance. Forecasts then feed a constrained BTC/ETH/SOL portfolio optimizer that accounts for user risk, covariance, uncertainty, and allocation caps.

## Important product boundaries

- ResFinance does not transfer fiat, native cryptocurrency, or tokens.
- Internal settlement credits are non-redeemable and have no claimed monetary value.
- The platform does not execute trades, hold exchange assets, or provide custody.
- Portfolio outputs are analytical scenarios, not guaranteed returns or financial advice.
- The AI assistant is read-only: it cannot modify records, sign actions, settle obligations, or trade.
- ResVault private keys and seeds must never leave the extension.
- Apache ResilientDB is the sole persistent application and research database.

## Current development status

Milestone 0 is active. The repository now pins ResilientDB, ResContract, ResVault, the toolchain, and the initial local models; defines the REST, security, and research contracts; and provides a reproducible feasibility harness. The official pinned ResVault implementation failed the key-isolation audit, so the approved path is a substantial hardened implementation that keeps wallet functionality in scope.

The milestone is not complete. Real four-replica durability and failure tests, ResContract lifecycle validation, ResilientDB-backed 100 MB artifact reconstruction, the signed settlement saga, hardened-wallet non-disclosure tests, and complete provider-period/license validation still need to pass. See the [Milestone 0 feasibility status](docs/feasibility.md).

Cloud and production deployment are intentionally deferred. Completing the local application will not imply cloud support or production readiness; deployment requires a separate ResilientDB cloud feasibility review and approved architecture decision record.

## Repository layout

```text
client/       React and TypeScript application
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
- [REST API contract](docs/rest-api-contract.md)
- [Security contract](docs/security.md)
- [Research protocol](docs/research-protocol.md)
- [ResVault pinned-source audit](docs/audits/resvault-2026-10-12.md)
- [ResilientDB ecosystem development references](docs/development-references.md)
- [Repository instructions for coding agents](AGENTS.md)

## License

See [LICENSE](LICENSE) for the repository license.
