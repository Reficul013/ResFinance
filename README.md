# ResFinance

ResFinance is a planned wallet-authenticated finance platform that connects personal budgeting, shared expenses, and explainable BTC/ETH/SOL portfolio analysis through one auditable financial record.

> **Project status:** Architecture and delivery planning are complete. Application implementation has not started. Local feasibility and integration work comes first; cloud and production deployment are currently on hold.

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

The repository is at the approved planning baseline. Work begins with local feasibility gates for ResilientDB, ResContract, ResVault, encrypted event storage, large artifact reconstruction, and BTC/ETH/SOL data availability. Feature development follows only after the required integration gates pass.

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
- [ResilientDB ecosystem development references](docs/development-references.md)
- [Repository instructions for coding agents](AGENTS.md)

## License

See [LICENSE](LICENSE) for the repository license.
