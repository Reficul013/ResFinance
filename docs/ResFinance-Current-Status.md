# ResFinance Current Status

Last updated: 2026-10-24

ResFinance uses the eight-milestone convention in
[`milestones/milestones.md`](milestones/milestones.md). Milestones 1–7 are complete for the
declared local development and non-commercial research scope. Milestone 8 is on
hold. Local completion does not establish cloud, production, commercial,
custody, trading, investment-advice, or independent-BFT readiness.

On 2026-10-24, the project owner finalized and accepted the ResWallet
functionality and Personal Finance dashboard for the declared local-development
scope. No remaining owner-side functionality or presentation tasks are tracked
for those two areas.

## Milestone 1: ResFinance Foundation — Architecture, Feasibility Gate & Platform Foundation

**Status:** Complete for local development and feasibility.

- Defined the architecture, REST, security, research, storage, and repository
  boundaries.
- Pinned ResilientDB, ResContract, the upstream ResVault audit reference,
  ResWallet dependencies, compilers, language runtimes, and model revisions.
- Passed all seven feasibility gates, including four-replica persistence and
  failure behavior, a verified 100 MiB artifact round trip, persistent
  ResContract execution, signed settlement, key-isolation boundaries, provider
  coverage, and failure enforcement.
- Delivered the React/Vite client foundation, FastAPI modular monolith,
  generated `/api/v1` client contract, encrypted append-only event and blob
  repositories, deterministic idempotency, projection rebuilds, and the local
  four-replica ResilientDB topology.
- Real-stack acceptance passed encrypted write, deduplication, full restart,
  readback, and deterministic projection rebuild without another database.
- The upstream ResVault audit failed the required custody boundary and led to
  the custom ResWallet design completed in Milestone 2.

Evidence:
[`milestones/milestone1-resfinance-foundation.md`](milestones/milestone1-resfinance-foundation.md).

## Milestone 2: ResWallet — Custom Hardened ResVault & Wallet Authentication

**Status:** Finalized and project-owner accepted for local development.

- Delivered the custom Manifest V3 ResWallet extension with Argon2id and
  AES-256-GCM seed protection, memory-only unlocked secrets, exact-origin
  messaging, extension-owned approvals, and background-only Ed25519 signing.
- Implemented challenge login, memory-only access tokens, HttpOnly refresh
  cookies, ResilientDB-backed session hashes, rotation, replay protection,
  revocation, and logout.
- Verified tamper, expiry, origin, network, replay, and locked-wallet defenses
  against the local stack, including restart persistence.
- Refined the wallet login and extension experience with ResFinance branding,
  a labeled public address, inline setup guidance, toolbar approval in the same
  browser window, live locked/unlocked status, Enter-key submission, visible
  wrong-password feedback, and a blinking locked-state indicator.
- Project-owner acceptance on 2026-10-24 closed the remaining ResWallet
  functionality and presentation tasks for the local-development scope.

Evidence:
[`milestones/milestone2-reswallet-wallet-authentication.md`](milestones/milestone2-reswallet-wallet-authentication.md).

## Milestone 3: Personal Finance — Dashboard & Smart Insights (Read-only AI)

**Status:** Finalized and project-owner accepted for local development.

- Delivered encrypted append-only Finance records, the fixed category catalog,
  income and expenses, budgets, recurring entries, compensating corrections,
  contract-backed receivables/payables, exact integer-cent summaries, and the
  versioned `finance-savings-v1` calculation.
- Added the authenticated Personal Finance dashboard, ledger-driven analytics,
  accessible states and charts, correction workflows, and consolidated data
  freshness and provenance.
- Added confirmed `ArchiveX` correction actions for active transactions,
  budgets, and recurring items. They append void/deactivation events and
  preserve the original audit record instead of deleting persisted history.
- Made the fixed direction-aware category catalog available immediately to new
  wallets and removed the category-creation step. Dashboard analytics cover
  category spending, a step-area running balance path by day within the month,
  and an exact six-month income, expense, and available-savings history.
  Budget utilization stays on the planning progress bars.
- Embedded Smart Savings Insights inside Personal Finance using
  wallet-authorized fact bundles, evidence-ID validation, deterministic
  fallback, bounded local-model selection, prompt-injection defenses, and
  prohibited-action refusals.
- Verified that the AI path is read-only and performs no ResilientDB writes,
  wallet signing, settlement, trading, or Finance mutation.
- Refined the Personal Finance presentation with a single three-form accordion,
  a compact row for cash flow, transactions, budgets, and commitments, and a
  bulleted dashboard guide that color-codes and explains actual, projected, and
  available savings.
- Added consistent section hierarchy for financial activity, trends, and Smart
  Savings Insights; simplified the entry accordion to one enlarged yellow
  boundary; applied the red, yellow, and teal theme palette to budget bars; and
  normalized the dashboard-guide body typography.
- Refined the embedded Insights workspace with balanced question and answer
  panels, exactly three suggested-question actions with lightbulb cues,
  width-efficient evidence and caveat grids, a yellow verified-fallback badge,
  explicit completion feedback, and a bounded 30-second request with retry
  guidance.
- Finalized the dashboard charts with viewport-timed entrance motion,
  visible budget-bar fills, an emphasized running-balance path, consistent
  title casing, and reduced-motion handling; expanded the dashboard guide to
  explain monthly review, append-only corrections, and read-only Insights.
- Project-owner acceptance on 2026-10-24 closed the remaining Personal Finance
  functionality and presentation tasks for the local-development scope.

Evidence:
[`milestones/milestone3-personal-finance-smart-insights.md`](milestones/milestone3-personal-finance-smart-insights.md).

## Milestone 4: Bill Split — Friends, Groups & Contractual Settlement

**Status:** Complete for local development.

- Delivered friends/groups, exact expense splits, participant decisions signed
  by ResWallet, obligation notifications, and the deployed
  `ResFinanceSettlement.sol` state machine.
- Implemented non-redeemable internal credits, partial and full settlement,
  immutable receipts, Finance propagation, and crash-safe reconciliation.
- Verified tamper and replay rejection and matching Group/Finance balances
  after a full ResilientDB and ResContract restart.
- Confined Group projection version, encrypted source-event count, and update
  time to the Data Freshness and Provenance footer.
- Reorganized the Friends & Groups dashboard around a Personal Finance-style
  hero, summary cards, a collapsible Update the group section, and paged
  activity tabs with filters. Signing and settlement behavior is unchanged.

Evidence:
[`milestones/milestone4-bill-split-contractual-settlement.md`](milestones/milestone4-bill-split-contractual-settlement.md).

## Milestone 5: Crypto Intelligence — Crypto Ingestion, Feature Store & Reproducible ML Research

**Status:** Complete for local, non-commercial research mechanics.

- Implemented Coin Metrics, CoinGecko, DefiLlama, and bounded GDELT adapters for
  exactly `BTC | ETH | SOL`, with availability timestamps, provenance, response
  hashes, license dispositions, explicit missingness, and idempotent ingestion.
- Persisted immutable observations, point-in-time feature rows, source masks,
  dataset manifests, research manifests, and encrypted model artifacts only in
  ResilientDB.
- Implemented deterministic baselines, LSTM, the clean-room three-asset
  MSPCIFormer adaptation, masked Adaptive Multi-Source Gating, ablations,
  chronological walk-forward evaluation, conformal intervals, and immutable
  promotion gates.
- The deterministic synthetic candidate was correctly rejected because its MAE
  was worse than naive. That rejection proves gate enforcement and is not a
  model-performance claim.
- Repeated deterministic CPU runs produced identical dataset and prediction
  hashes, and all 39 encrypted research artifacts restored byte-for-byte from
  the real four-replica ResilientDB stack.
- Fixed point-in-time source alignment. The feature builder previously looked
  up non-market observations for the row's own calendar day only, so GDELT
  sentiment (published two days after the day it describes) never reached a
  model. Rows now use the newest non-market observation already available at
  decision time, record each feature's age in `feature_age_days`, and mask a
  source once it is older than three days. Prices remain strictly same-day.

Evidence:
[`milestones/milestone5-crypto-intelligence-research.md`](milestones/milestone5-crypto-intelligence-research.md).

## Milestone 6: Crypto Intelligence — Risk & Portfolio Dashboard

**Status:** Complete for local development.

- Delivered the versioned risk questionnaire, constrained long-only
  BTC/ETH/SOL optimization, Finance-linked default capital, exact-cent
  allocations, immutable forecast provenance, and non-mutating amount
  scenarios.
- Implemented Ledoit-Wolf covariance, 15-day scaling, positive-semidefinite
  repair, CLARABEL/SCS solving, and a constrained minimum-variance fallback.
- Delivered the Crypto Intelligence dashboard and fail-closed handling for
  stale, synthetic, corrupted, or unpromoted forecast inputs.

Evidence:
[`milestones/milestone6-crypto-intelligence-dashboard.md`](milestones/milestone6-crypto-intelligence-dashboard.md).

## Milestone 7: Deliverables — Cross-dashboard Integration & Local Handoff

**Status:** Complete for the declared local development and research scope.

- Completed shared navigation, wallet-scoped notifications, theme and session
  behavior, provenance presentation, and the connected Finance → Groups →
  Crypto Intelligence → Smart Insights journey.
- The authenticated header keeps Personal Finance, Friends & Groups, and
  Crypto Intelligence as the three primary tabs. Both the header and welcome
  screen place Medium before the repository link and theme control; the header
  also includes notifications and logout. New sessions default to Dark Mode,
  explicit Light Mode preferences persist, and brand selection or logout
  returns to the ResWallet welcome screen.
- Added bounded preflight, start, status, restart, logs, stop, and confirmed
  reset operations; explicit ingestion and reconciliation workers; an operator
  guide; and a continuous real two-wallet Chromium journey over ResWallet,
  FastAPI, four ResilientDB replicas, and ResContract.
- Kept the original provider-backed candidate rejected. A separately
  predeclared forward candidate tied naive MAE at `0.0529717654`, achieved
  `88.05%` interval coverage, passed the unchanged promotion gate, and produced
  a provenance-linked 15-day BTC/ETH/SOL snapshot.
- Verified the normal recommendation, exact-cent allocations, Finance-derived
  default amount, non-mutating scenario, fail-closed invalid inputs, restart
  persistence, and read-only Insights behavior.
- Replaced the reliability-shrinkage forecast with the
  `no-change-centre-native-heads-v1` policy: the expected return is fixed at
  zero, while p10/p50/p90 and P(up) come from the model's own quantile and
  direction heads with a split-conformal adjustment. Assets whose sentiment or
  on-chain source is missing or stale at decision time switch to the persisted
  market-only model. Schema-v1 calibrations keep their original behavior.
- Implemented forward protocol v2 (`untouched-forward-holdout-v2`), predeclared
  on 2026-10-27:
  - 15/20/30-day horizons;
  - three-seed ensembles (11, 23, 37) trained for 100 epochs at learning rate 0.001;
  - a full-year 2024-03-01 to 2025-02-28 calibration window and a 30-day embargo;
  - holdout decisions from 2025-04-01;
  - schema-v3 manifests validated on persistence;
  - deterministic seed-ensemble checkpoint bundles.

  The published snapshot stays at 15 days.
- Known limitation: a provider-data smoke run of protocol v2 did not reproduce the
  exploratory study's gain, so do not treat a v1-gate pass as evidence of better
  ranges.
  - **15-day results:** the deployable forecast covered 92.0% at interval score
    0.525, against 84.3% and 0.465 for no-change.
  - **20 and 30 days:** it was about level with no-change (0.567 vs 0.557; 0.689 vs
    0.689).
  - **Cause 1 (no news):** news ingestion ends on 2025-01-01, so every holdout
    decision used the market-only fallback.
  - **Cause 2 (calibration mismatch):** the single conformal adjustment was fitted
    mostly on the adaptive model's validation outputs, then applied to the fallback
    model.
  - **Fix needs a new protocol:** calibrating each path separately and restoring
    ongoing news ingestion require a newly predeclared protocol scored on
    prospective data. The holdout from 2025-04-01 has already been observed.
- Predeclared (2026-10-28) and implemented prospective protocol v3
  (`prospective-forward-v3`), which addresses both causes:
  - **News:** a GDELT DOC 2.0 adapter (provider `gdelt-doc`) for backfill and daily
    ingestion. It drops GDELT outage days with a same-weekday volume rule, and v3 runs
    refuse the one-time GKG export.
  - **Calibration:** separate split-conformal adjustments for the adaptive model (on
    fresh-source validation samples), the market-only fallback and the no-change
    baseline. Each path's adjustment is applied only to its own forecasts.
  - **Evaluation:** no retrospective holdout.
    - The schema-v4 run is frozen once. Each day, an immutable ResilientDB ledger entry
      records the deployable and no-change forecasts. It is accepted only if issued
      within 24 hours of its decision time.
    - The `forecast-promotion-prospective-v1` gate scores the earliest 90 decision dates
      per horizon. With the 30-day horizon, the earliest decision is late February 2027.
  - **Operator steps:** `scripts/milestone9/run_prospective.py` (`ingest`, `freeze`,
    `issue`, `score`, `promote`).
  - **Not yet started on the local stack:** no v3 run has been frozen in ResilientDB,
    and no daily scheduler is installed. The prospective window starts at the first
    decision date after the freeze.
  - **Provider-data smoke freeze (2026-10-28).** The full 100-epoch v3 run (954 s) was
    run on cached provider data through 2026-10-24, outside ResilientDB:
    - **News is back.** Sentiment is available on 96% of 2025 rows and 95% of 2026
      rows; under v2, news ended on 2025-01-01. Of 2,389 days per asset, GDELT
      returned no point for 39, and the outage rule dropped 32. October 2026 alone had
      five outage days and three missing days, so the fallback path will be used.
    - **Fallback use is small.** The validation fallback share fell to 1.4%, against
      14.8% under v2 (and 100% on the v2 holdout).
    - **The paths need different widening.** Adjustments at 15/20/30 days:

      | Path | 15 days | 20 days | 30 days |
      |---|---|---|---|
      | Primary | 0.039 | 0.067 | 0.115 |
      | Fallback | 0.000 | 0.014 | 0.077 |

      The single v2 adjustment therefore over-widened fallback ranges.
    - **Warning, not evidence.** Calibration was fitted on the validation window, so
      both forecasts cover about 80% there. At that coverage, the primary path's
      ranges were still wider than no-change's:

      | Horizon | Primary path | No-change |
      |---|---|---|
      | 15 days | 0.297 | 0.286 |
      | 20 days | 0.387 | 0.343 |
      | 30 days | 0.492 | 0.453 |

      The prospective gate may therefore fail. Only the gate decides.

Evidence:
[`milestones/milestone7-cross-dashboard-local-handoff.md`](milestones/milestone7-cross-dashboard-local-handoff.md)
and
[`local-operator-guide.md`](local-operator-guide.md).

## Milestone 8: Future Scope — Production Hardening & Deployment (On Hold)

**Status:** On hold.

- No cloud infrastructure, production pipeline, or production-readiness claim
  is authorized.
- Resumption requires a separate ResilientDB cloud feasibility review and an
  approved ADR covering networking, persistent storage, restart recovery,
  replica failure, failure domains, operations, key management, backups,
  observability, and deployment automation.
- Local development, integration, research, security, browser, accessibility,
  load, and chaos testing remain in scope.

Evidence:
[`milestones/milestone8-production-hardening-deployment.md`](milestones/milestone8-production-hardening-deployment.md).

## Maintenance rule

Update this file whenever a pushed change materially alters milestone scope,
status, user-visible behavior, verification evidence, readiness, or known
limitations. Keep the root README focused on the product, architecture,
boundaries, setup, repository layout, and links to current status and evidence.
