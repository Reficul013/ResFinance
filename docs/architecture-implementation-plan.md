# ExpoLab Finance Platform Architecture and Delivery Plan

Status: Approved planning baseline for local implementation; cloud deployment is on hold

Last reviewed: 2026-10-12

Implementation status: Not started

Deployment status: On hold pending a separate, evidence-backed ResilientDB cloud feasibility review. Current work is limited to local development, integration, research, and end-to-end validation.

## 1. Summary and Product Boundaries

ExpoLab will be a wallet-authenticated finance platform with exactly three interconnected dashboards:

1. **Personal Finance** — income, expenses, budgets, savings, receivables, payables, and financial insights.
2. **Friends & Groups** — shared expenses, participant approval, obligations, internal-credit settlements, and immutable receipts.
3. **Crypto Investments** — BTC, ETH, and SOL market analysis, forecasts, risk profiling, portfolio allocation, scenarios, and AI explanations.

Non-negotiable boundaries:

- Apache ResilientDB is the only persistent application and research database.
- No PostgreSQL, MongoDB, SQLite, DuckDB, Redis, Parquet-based persistence, or external object store.
- Crypto support is hard-limited to `BTC | ETH | SOL` at API, ingestion, model, UI, and test boundaries.
- Frontend-to-backend communication is REST under `/api/v1`.
- ResVault performs authentication and signs contract-affecting actions.
- ResContract executes meaningful obligation and settlement-credit state transitions.
- V1 does not transfer fiat or native cryptocurrency, execute trades, provide exchange custody, or claim that internal credits have monetary value.
- The AI agent is read-only and cannot alter records, sign actions, settle obligations, or trade.
- Cloud and production deployment work is out of scope until explicitly resumed after ResilientDB cloud compatibility, operations, and failure behavior are validated.

## 2. Target Architecture

```text
                         Reviewed ResVault extension
                      challenge + signed action intents
                                  │
┌─────────────────────────────────▼──────────────────────────────────┐
│ React / TypeScript / Vite                                         │
│ Shared shell                                                      │
│ ├── Personal Finance                                              │
│ ├── Friends & Groups                                              │
│ └── Crypto Investments                                            │
│ REST client generated from OpenAPI; no direct database/GraphQL    │
└───────────────────────────────┬────────────────────────────────────┘
                                │ HTTPS REST /api/v1
┌───────────────────────────────▼────────────────────────────────────┐
│ FastAPI modular monolith                                           │
│ Auth │ Finance │ Groups │ Crypto │ Research │ Portfolio │ AI       │
│                                                                   │
│ Application services and domain events                            │
│ ├── ResilientDB repository adapter                                │
│ ├── ResContract private gateway                                   │
│ ├── Market/sentiment/on-chain provider adapters                   │
│ └── Hugging Face inference adapters                               │
└───────────────┬─────────────────┬───────────────────┬──────────────┘
                │                 │                   │
       ┌────────▼────────┐ ┌──────▼───────┐  ┌────────▼────────────┐
       │ ResilientDB     │ │ ResContract  │  │ Singleton workers   │
       │ 4-replica PBFT  │ │ private API  │  │ ingestion / ML /    │
       │ event + blobs   │ │ Solidity     │  │ reconcile / AI      │
       └─────────────────┘ └──────┬───────┘  └─────────────────────┘
                                  │
                           ResilientDB state
```

### Dashboard dependencies

| Producer | Consumer | Contract |
|---|---|---|
| ResVault | All dashboards | Login challenge signing; explicit signatures for split approval, credit funding, and settlement |
| Groups | Finance | Accepted obligations become receivables/payables; confirmed contract settlements update finance balances and savings |
| Finance | Crypto | Versioned available-savings calculation provides the default investment amount |
| Market/ML pipeline | Crypto | Immutable feature snapshots, forecasts, confidence intervals, and model provenance |
| Risk profile | Portfolio optimizer | Converts the user score into a versioned risk-aversion and allocation policy |
| All three domains | AI agent | Read-only fact bundle with record IDs, timestamps, and provenance |
| Crypto scenario | Finance | No mutation; an alternate amount only changes the scenario response |

### Frontend

- Shared authenticated shell with `/finance`, `/groups`, and `/crypto`; settings are shared UI, not a fourth dashboard.
- React Router, TanStack Query, generated OpenAPI TypeScript types, React Hook Form, and Zod.
- Shadcn/UI and Tailwind for accessible, responsive components.
- Recharts for budgets, cash flow, allocations, risk, and forecast evaluation.
- TradingView Lightweight Charts for BTC/ETH/SOL price and forecast overlays.
- Access tokens held in memory; no application records in browser local storage or IndexedDB.
- Every screen displays data freshness and provenance. Forecasts and allocations carry a non-advice disclaimer.

### Backend and workers

Use one FastAPI codebase with clear module boundaries rather than premature microservices:

- **API process:** REST, validation, authentication, orchestration, OpenAPI.
- **Ingestion worker:** market, on-chain, and sentiment collection.
- **ML worker:** datasets, training, evaluation, forecasts, and artifact persistence.
- **Reconciliation worker:** repairs event indexes and contract-to-finance saga interruptions.
- **AI worker:** grounded, read-only explanations with deterministic fallback.

Workers are singleton deployments in V1. Jobs, leases, status, failures, and retry records are stored in ResilientDB; process memory and temporary computation files may be ephemeral.

### ResilientDB data architecture

Use append-only events, deterministic keys, and prefix/range queries. Do not depend on a “list everything” endpoint or treat the current Python ORM as a production repository layer.

Core envelope:

```text
DomainEvent {
  schema_version,
  event_id,
  event_type,
  occurred_at_utc,
  tenant_id,
  actor_id,
  aggregate_type,
  aggregate_id,
  aggregate_version,
  idempotency_key,
  encrypted_payload,
  payload_hash,
  source_references[],
  contract_receipt?
}
```

Key families:

- `evt:{tenant}:{type}:{aggregate}:{timestamp}:{event_id}`
- `idx:{tenant}:{subject}:{stream}:{timestamp}:{event_id}`
- `cmd:{tenant}:{idempotency_key}`
- `mkt:{asset}:{interval}:{timestamp}:{provider}:{revision}`
- `chain:{asset}:{metric}:{timestamp}:{provider}:{revision}`
- `sent:{asset}:{timestamp}:{model_hash}:{revision}`
- `feat:{dataset_hash}:{asset}:{timestamp}`
- `forecast:{model_hash}:{asset}:{as_of}:{horizon}`
- `run:{run_id}:manifest`
- `blob:{sha256}:{chunk_number}`
- `snapshot:{projection}:{subject}:{as_of}:{hash}`

Rules:

- Events are immutable; corrections append compensating events.
- Secondary indexes and projections are rebuildable.
- Generated model artifacts are compressed, split into 256 KiB content-addressed chunks, stored in ResilientDB, and verified against a manifest hash.
- Temporary training files are deleted after successful verified persistence.
- Sensitive payloads use AES-256-GCM envelope encryption. Local development uses non-production key handling that never commits secrets. A production KMS design remains deferred with the deployment plan; when resumed, KMS may wrap per-user and per-group data keys but must never store application records.
- Cleartext indexes contain only pseudonymous identifiers, record type, schema version, and timestamps.
- Erasure uses a tombstone plus destruction of the applicable data-encryption key; immutable ciphertext may remain replicated.
- Money uses integer USD cents. Crypto quantities and prices use validated decimal strings, never binary floating point.

### REST and shared types

Principal endpoints:

- Authentication: `POST /auth/challenges`, `POST /auth/sessions`, `POST /auth/refresh`, `DELETE /auth/sessions/current`.
- Finance: transactions, budgets, recurring items, summaries, savings, obligations, and insights.
- Groups: groups, members, expenses, splits, approvals, obligations, settlements, balances, and receipts.
- Crypto: asset catalog, prices, signals, forecasts, risk profile, recommendations, saved analyses, and non-mutating scenarios.
- AI: `POST /assistant/explain`.
- Research administration: run submission, status, manifest, metrics, and approved model promotion.

All write endpoints require an `Idempotency-Key`. Errors use RFC 9457 Problem Details. Responses expose `event_id`, `projection_version`, and relevant source or contract receipt IDs.

Shared public types:

```text
CryptoAsset = BTC | ETH | SOL
Money = { currency: "USD", minor_units: int64 }
SignedIntent = {
  version, intent_id, action, actor_public_key, actor_address,
  resource_id, parameters_hash, nonce, issued_at, expires_at,
  audience, network_id, signature
}
Forecast = {
  asset, as_of, horizon_days, expected_return,
  probability_up, p10, p50, p90, model_hash, dataset_hash
}
PortfolioRecommendation = {
  source_savings_event, capital, risk_score, horizon_days,
  weights, dollar_allocations, forecast_ids, policy_version, warnings
}
```

Signed intents use RFC 8785 canonical JSON and Ed25519. The backend verifies signature, origin/audience, network, expiry, nonce, payload hash, and expected resource state before invoking ResContract.

### Wallet and smart-contract behavior

Milestone 0 will audit the pinned official ResVault implementation before choosing a maintenance strategy. The audit must trace seed and private-key handling across extension storage, background code, content scripts, page messaging, network requests, and logs. It will produce one of three evidence-backed outcomes:

1. Use the pinned upstream implementation unchanged if it satisfies every key-isolation and signed-intent requirement.
2. Maintain a minimal fork, documented by an architecture decision record, if narrowly scoped compatibility or security patches are required.
3. Undertake a documented substantial hardening fork or ResVault-compatible redesign if the implementation cannot be made safe with a minimal patch. The larger effort must preserve the required ResVault behavior and pass the same security contract; complexity alone does not remove wallet-dependent functionality from scope.

Whichever implementation is approved will:

- Remain pinned to a reviewed upstream Apache commit.
- Keep signing inside the extension background context.
- Return only the public key, address, and signature to the page.
- Store only an Argon2id-derived, AES-GCM-encrypted seed; the password and decrypted seed remain memory-only while unlocked.
- Enforce an application-origin allowlist and explicit user approval for contract-affecting signatures.
- Support challenge signing, split approval, settlement authorization, and receipt verification.

The current planning review identified potential exposure in the page-messaging and key-storage paths, but this is a hypothesis to validate against the pinned source rather than a pre-authorized large fork. The audit will record concrete source references, executable key-leak tests, and the minimum required remediation before Milestone 2 begins. Relevant upstream surfaces include ResVault’s [`content.js`](https://github.com/apache/incubator-resilientdb/blob/master/ecosystem/tools/resvault/public/content.js) and [`background.js`](https://github.com/apache/incubator-resilientdb/blob/master/ecosystem/tools/resvault/public/background.js).

`ResFinanceSettlement.sol` will implement:

- Wallet registration by derived address and public-key hash.
- Controlled issuance of explicitly non-redeemable settlement credits.
- Split creation with payer, participants, exact USD-cent obligations, and immutable expense reference.
- Per-participant signed approval or rejection.
- Partial or full settlement from debtor credits to creditor credits.
- Replay, duplicate, insufficient-balance, overpayment, and post-settlement mutation prevention.
- `PENDING`, `OPEN`, `PARTIALLY_SETTLED`, `SETTLED`, `REJECTED`, and `CANCELLED` states.
- Queryable balances, obligations, intent hashes, nonces, and settlement receipts.

ResContract does not currently establish wallet signature authorization by itself. Therefore:

- Its GraphQL/CLI service remains private and firewall-restricted.
- Only the FastAPI contract gateway may reach it.
- The gateway verifies the Ed25519 signed intent before supplying the compatible caller address.
- The contract records the actor address, signed-intent hash, and nonce.
- This is a permissioned gateway design, not a claim of fully trustless end-to-end wallet execution.

The contract is authoritative for obligation and settlement state. Finance is updated only after confirmed contract state. A saga and reconciler repair crashes between the contract operation and its corresponding finance event.

### Crypto data, ML, portfolio, and AI

Data adapters:

- Coin Metrics Community for daily BTC/ETH/SOL price, volume, capitalization, and available BTC/ETH on-chain metrics.
- CoinGecko for current quotes and UI fallback.
- DefiLlama for SOL TVL and stablecoin-supply proxies because the audited Coin Metrics Community catalog does not expose comparable native SOL on-chain series.
- GDELT GKG historical tone/coverage and DOC API live news metadata; do not persist full copyrighted articles.
- `facebook/bart-large-mnli`, pinned by model revision and hash, for supplemental bullish/bearish/neutral headline classification.

The adapters retain source URL/query, retrieval time, provider revision, license metadata, row counts, checksums, availability time, and missingness. Official references: [Coin Metrics API v4](https://docs.coinmetrics.io/api/v4/), [CoinGecko API](https://www.coingecko.com/en/api), [DefiLlama API](https://api-docs.defillama.com/), and [GDELT DOC 2.0](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/).

Research dataset V1:

- Daily UTC observations from 2020-04-10 through 2025-01-01.
- Exactly BTC, ETH, and SOL.
- Market, sentiment, and asset-specific on-chain/proxy channels.
- Point-in-time joins using source availability timestamps.
- Missing-source masks are model inputs; unavailable metrics are not silently imputed as zero.

Model:

- Separate market, sentiment, and on-chain encoders.
- Masked softmax Adaptive Multi-Source Gating per asset and time step.
- Multi-scale patching, channel-independent Transformer blocks, and learnable aggregation following the MSPCIFormer design.
- Horizons: 1, 3, 5, 7, and 15 days.
- Heads for expected return, direction probability, and p10/p50/p90 quantiles.
- Split-conformal calibration on validation windows.
- Required ablations: market-only, fixed equal fusion, adaptive gating, and one-source-removed variants.
- Baselines: naive last value/zero return, linear model, and an LSTM or equivalent sequence baseline.

The published MSPCIFormer experiment used eight input assets and only ADA/BTC/ETH targets; this project is therefore a documented three-asset adaptation, not an exact reproduction. The paper and author repository remain provenance inputs, but source code must not be copied until its absent license is resolved: [MSPCIFormer paper](https://onlinelibrary.wiley.com/doi/10.1111/exsy.70343), [author repository](https://github.com/cmajorsolo/MSPCIFormer). The Gurgul baseline is similarly adapted to the permitted data and assets: [arXiv paper](https://arxiv.org/abs/2311.14759), [journal DOI](https://doi.org/10.1016/j.ijforecast.2025.02.007).

Every research run persists:

- Git commit, configuration, code and dependency hashes.
- Docker image digest, Python/PyTorch versions, hardware, deterministic seed, and determinism flags.
- Input record IDs, dataset manifest/hash, split boundaries, preprocessing parameters, and feature schema.
- Checkpoint, predictions, metrics, plots, gate weights, warnings, and parent-run relationship.
- Five expanding walk-forward folds with embargo and no random shuffling.
- MAE, RMSE, directional accuracy, Brier score, interval coverage/width, Sharpe ratio, maximum drawdown, and transaction-cost sensitivity.

Portfolio optimization:

- Long-only BTC/ETH/SOL weights summing to one.
- Ledoit-Wolf covariance from trailing daily returns.
- Fifteen-day forecast as the default expected-return horizon.
- Objective: maximize uncertainty-adjusted expected return minus risk-score-dependent variance.
- Default caps: BTC 80%, ETH 60%, and SOL from 10% at risk score 0 to 35% at risk score 100.
- CLARABEL solver with SCS fallback; nearest positive-semidefinite covariance repair and minimum-variance fallback.
- Default capital comes from the versioned finance savings calculation.
- “Analyze Another Amount” changes dollar allocations in an isolated scenario and never changes finance records or the default savings source.

AI agent:

- Receives only a structured, authorized fact bundle assembled by domain services.
- Uses a pinned Hugging Face instruction model selected during the feasibility milestone from permissively licensed models small enough for the target VM.
- May explain budgets, obligations, forecasts, gating, uncertainty, and portfolio allocations.
- Returns structured `summary`, `evidence`, `caveats`, and `follow_up_questions`.
- Cannot call mutation tools or access ResilientDB, ResContract, ResVault, or external trading systems directly.
- Falls back to deterministic templates if evidence coverage or model confidence is insufficient.

## 3. ResilientDB Feasibility Conclusions

The integration is **conditionally feasible**, with mandatory validation before feature development.

- ResilientDB currently exposes KV, versioned history/range concepts, REST/GraphQL components, Python tooling, ResContract, and ResVault in the official Apache repository. However, the SDK/ORM surface is not mature enough to adopt directly as the domain persistence layer. ExpoLab needs a narrow, tested repository adapter. [Apache ResilientDB repository](https://github.com/apache/incubator-resilientdb/blob/master/README.md)
- Some advertised or older “read all” behavior is not reliable in the current KV HTTP implementation. Queries must use known deterministic keys and prefix ranges. [Current KV service implementation](https://github.com/apache/incubator-resilientdb/blob/master/service/tools/kv/api_tools/kv_service_tools.cpp)
- ResContract can create, compile, deploy, and execute Solidity contracts, but its service boundary does not provide the required wallet-signature verification. Self-hosting, network isolation, and the signed-intent gateway are therefore mandatory. [ResContract source](https://github.com/apache/incubator-resilientdb/tree/master/ecosystem/smart-contract/rescontract)
- ResVault must pass the pinned-source key-isolation audit before its implementation is accepted. Upstream reuse is preferred when it passes; otherwise the project will implement the evidence-backed minimal patch or, when necessary, a documented substantial hardening fork or compatible redesign. Wallet-dependent functionality remains in scope under every outcome. [ResVault source](https://github.com/apache/incubator-resilientdb/tree/master/ecosystem/tools/resvault)
- ResSQL is excluded because its implementation is DuckDB-based and conflicts with the sole-database constraint.
- A four-replica local Docker setup is suitable for development but does not provide independent Byzantine fault domains. No cloud or production resilience claim will be made while deployment is on hold.
- Large model artifacts remain feasible only if the chunked round-trip spike succeeds. No fallback database or object store is permitted.

Cloud deployment is not part of the current feasibility gate. If deployment work is resumed, it requires a new decision record and a separate spike proving that the pinned ResilientDB stack can be operated safely in the selected cloud environment before any infrastructure is provisioned.

Go/no-go validation must prove:

1. Commit, get, prefix range, history/version, restart durability, and one-replica failure behavior.
2. A 100 MB checkpoint can be persisted in 256 KiB chunks and reconstructed with identical SHA-256.
3. A Solidity contract can be compiled, deployed, executed, queried, and restarted on the pinned stack.
4. A signed ResVault settlement travels through REST, passes backend verification, changes contract state, and produces a ResilientDB finance event.
5. The browser page, network traffic, server, and logs never receive a private key or seed.
6. BTC/ETH/SOL provider samples and the fixed research-period data can be acquired with recorded license/provenance.
7. If any test fails, work stops at the adapter or upstream integration layer; another persistent database is not introduced.

## 4. Dependency-Ordered Roadmap

### Milestone 0 — Architecture and feasibility gate

- Populate the root `AGENTS.md` and add reviewed architecture, feasibility, REST-contract, security, and research-protocol documents.
- Pin the ResilientDB, ResContract, ResVault, compiler, Python, Node, and model revisions.
- Audit the pinned official ResVault implementation and record whether unchanged upstream use, a minimal fork, or a substantial documented hardening effort is warranted.
- Run all seven go/no-go tests above.
- Produce a signed decision record for any local fork or compatibility patch.

**Acceptance:** every feasibility test passes in CI or the project remains blocked with reproducible failure evidence.

### Milestone 1 — Platform foundation

- Establish React/Vite and FastAPI modular boundaries, OpenAPI generation, error format, validation, linting, and CI.
- Implement the ResilientDB event/blob repository, encryption envelope, deterministic keys, idempotency, projection rebuild, and provider interfaces.
- Provide four-node development Compose topology and private service networking.

**Acceptance:** contract tests write, restart, read, rebuild, and deduplicate encrypted sample events without another database.

### Milestone 2 — Hardened wallet and authentication

- Implement the Milestone 0 ResVault audit decision: use the pinned upstream implementation unchanged when it passes, apply the approved minimal patches when sufficient, or complete the documented substantial hardening fork or compatible redesign when required.
- Implement challenge login, in-memory access tokens, refresh-session hashes in ResilientDB, logout/revocation, address derivation, and signed-intent verification.
- Add replay, tamper, expiry, wrong-origin, wrong-network, and locked-wallet defenses.

**Acceptance:** approved challenges authenticate; all altered or replayed intents fail; automated inspection finds no key leakage.

### Milestone 3 — Personal Finance dashboard

- Implement income/expense events, categories, budgets, recurring entries, summaries, savings calculation, and receivable/payable projections.
- Build accessible charts, validation, empty/loading/error states, and provenance views.
- Version the savings formula used by Crypto.

**Acceptance:** unit and Playwright tests reproduce balances from events, budget alerts, monthly savings, and projection rebuilds exactly.

### Milestone 4 — Groups and contractual settlement

- Implement groups, membership, expenses, split validation, participant approval, obligation projections, and notifications.
- Deploy `ResFinanceSettlement.sol`.
- Implement non-redeemable credit issuance, partial/full settlements, receipts, finance propagation, and saga reconciliation.

**Acceptance:** multi-user E2E test creates a split, obtains approvals, rejects unsigned/tampered actions, settles partially and fully, prevents overpayment/replay, and shows matching Group and Finance balances after an injected crash.

### Milestone 5 — Crypto ingestion and feature store

- Add Coin Metrics, CoinGecko, DefiLlama, and GDELT adapters.
- Persist immutable raw observations, derived features, availability masks, licenses, and checksums.
- Enforce the three-asset enum at every boundary.

**Acceptance:** a repeat ingestion is idempotent, provider failure does not corrupt existing data, point-in-time joins pass leakage tests, and any fourth asset is rejected.

### Milestone 6 — Reproducible ML research

- Implement baselines, the three-asset MSPCIFormer adaptation, Adaptive Multi-Source Gating, walk-forward evaluation, conformal intervals, ablations, and artifact persistence.
- Add deterministic smoke datasets generated in test code and a full research-run manifest.
- Promote models only through explicit evaluation criteria and an immutable promotion event.

**Acceptance:** repeated CPU smoke runs have identical dataset/prediction hashes; full runs retain complete provenance; adaptive gating is reported against every required baseline without overstating statistical significance.

### Milestone 7 — Risk, portfolio, and Crypto dashboard

- Implement questionnaire scoring, policy versioning, CVXPY optimization, fallback behavior, forecasts, chart overlays, allocations, and non-mutating scenarios.
- Connect the default amount to Finance savings through an immutable source event ID.

**Acceptance:** weights satisfy every constraint, dollar allocations reconcile to the input amount, stale forecasts are rejected, and scenarios leave Finance unchanged.

### Milestone 8 — Read-only AI and end-to-end integration

- Benchmark and pin the local Hugging Face instruction model.
- Implement authorized fact bundles, evidence-linked generation, refusal rules, template fallback, and prompt-injection defenses.
- Complete cross-dashboard navigation and in-app notifications.

**Acceptance:** responses cite only supplied facts, unsupported questions trigger a caveat/fallback, and no AI path can invoke a write or wallet operation.

### Milestone 9 — Production hardening and deployment — ON HOLD

- Do not provision cloud infrastructure or implement a production deployment pipeline until this milestone is explicitly resumed.
- Before resumption, validate the pinned ResilientDB stack in the proposed cloud environment, including networking, persistent storage, restart recovery, replica failure, operational support, and independent failure domains.
- If that validation passes, define the deployment architecture in an ADR before implementing TLS/reverse proxy, static frontend hosting, API/workers, private ResContract, KMS integration, backups, observability, or deployment automation.
- Local load, accessibility, browser, chaos, and security testing may continue because it also supports implementation quality.

**Acceptance:** deferred. When resumed, acceptance criteria must be re-approved using evidence from the selected cloud environment. Until then, completion of Milestones 0–8 does not imply production readiness or cloud support.

## 5. Test Strategy and Risk Gates

Required suites:

- **Frontend:** Vitest component/state tests, generated-client compatibility, accessibility, and Playwright journeys across all three dashboards.
- **Backend:** Pytest unit, REST contract, authorization, encryption, idempotency, reducer, and provider-adapter tests.
- **ResilientDB:** real four-node integration, restart durability, range/history behavior, blob reconstruction, projection repair, and replica-loss tests.
- **Wallet/security:** origin isolation, private-key non-disclosure, locked-state behavior, replay/tamper/expiry rejection, and session revocation.
- **Contracts:** state transitions, authorization boundary, arithmetic, partial settlement, overpayment, duplicate nonce, cancellation, and receipt lookup.
- **ML:** no-lookahead joins, deterministic hashes, chronological folds, missing-source masks, baseline/ablation comparison, interval coverage, and artifact restoration.
- **Portfolio:** weight/cap invariants, solver failure, PSD repair, stale forecast, zero savings, and scenario non-mutation.
- **AI:** evidence coverage, hallucination, prompt injection, cross-user isolation, prohibited action requests, and deterministic fallback.

Principal risks and enforced responses:

- **SDK/API maturity:** isolate all upstream behavior behind adapters and pin commits.
- **Wallet key exposure:** choose unchanged upstream use, a minimal patch, or substantial hardening from audit evidence. Do not remove wallet-dependent functionality from scope because the required work is large, and do not accept the selected implementation until it passes key-leak tests.
- **Caller spoofing in ResContract:** private network plus mandatory signed gateway; never expose the contract service publicly.
- **Non-atomic contract/KV writes:** authoritative contract state, idempotent saga, and reconciliation worker.
- **Large artifact limits:** validate chunking before ML work; improve ResilientDB/configuration rather than add object storage.
- **Immutable sensitive data:** encrypt before persistence, minimize indexes, and use cryptographic erasure.
- **Provider gaps and drift:** availability masks, source revisions, fallback adapters, and no assumption of uniform SOL metrics.
- **Paper/code licensing:** reimplement from the published method unless explicit reuse permission or a license is obtained.
- **Research divergence:** label the work a three-asset adaptation and report dataset/provider differences.
- **Unvalidated cloud operation:** keep deployment on hold and do not claim production or BFT resilience. Any future deployment must prove that replicas span independent failure domains.
- **Internal-credit interpretation:** label credits non-redeemable and non-monetary throughout UI, API, and documentation.
- **LLM factuality:** evidence-bound read-only responses and deterministic fallback.
- **Financial harm:** no trade execution, no guaranteed-return language, and visible uncertainty/non-advice notices.

## 6. Root `AGENTS.md` Contract

The existing empty root `AGENTS.md` will be the first repository file populated after plan approval. It will stay concise and point to detailed architecture and research documents, following Codex’s hierarchical instruction behavior described in the [OpenAI Codex Prompting Guide](https://developers.openai.com/cookbook/examples/gpt-5/codex_prompting_guide).

It will establish these development conventions and non-negotiable rules:

- ResilientDB is the sole persistent application/research database; ResSQL, DuckDB, local artifact persistence, and hidden test databases are prohibited.
- Only BTC, ETH, and SOL may appear in crypto domain types, providers, models, UI, or fixtures.
- Browser code communicates with application services only through generated REST clients.
- No browser code may contact ResilientDB, ResContract GraphQL, or contract CLI endpoints.
- ResVault seeds/private keys never leave the extension; contract-affecting commands require a verified signed intent.
- Contract state is authoritative for obligations and settlements; Finance changes only from confirmed receipts.
- Sensitive values are encrypted before ResilientDB; secrets, private keys, raw passwords, and PII never enter logs.
- Domain records are append-only, schema-versioned, idempotent, UTC-based, and reducer-rebuildable.
- Money uses integer minor units or validated decimals; binary floats are forbidden for monetary calculations.
- Scenario analysis cannot alter Finance or the default savings source.
- AI is read-only and evidence-bound.
- Every ML run requires data/code/config/environment/model hashes, chronological splits, fixed seeds, and complete manifests.
- No MSPCIFormer source is copied until licensing is resolved.
- Python uses type-checked domain boundaries, Ruff, mypy, and Pytest; TypeScript uses strict mode, ESLint, Prettier, Vitest, and generated API types.
- FastAPI/Pydantic transport types do not replace domain models; infrastructure imports must not leak into domain modules.
- Every behavioral change includes tests at the lowest appropriate layer plus an integration test for cross-module behavior.
- Architecture exceptions require an ADR and explicit review; failures never justify silently introducing another database.
- Directory boundaries are:
  - `client/src/{app,features,components,lib}`
  - `server/app/{api,domain,application,infrastructure,workers}`
  - `blockchain/{contracts,adapter,tests}`
  - `ml/{data,features,models,evaluation,portfolio}`
  - `tests/{contract,integration,e2e}`

## 7. Locked Assumptions

- USD is the only fiat denomination in V1.
- Group settlement uses internal, non-redeemable ledger credits; no fiat, native BTC/ETH/SOL, or token transfer occurs.
- Free-first data adapters are the default, with provider variability accepted and recorded.
- Research baseline dates are fixed; live inference uses the latest completed UTC day.
- ResVault and ResContract are pinned and self-hosted. ResVault is used unchanged only if the Milestone 0 audit proves it meets the security contract; otherwise an explicitly documented minimal or substantial hardening implementation is maintained, according to the evidence.
- Cloud and production deployment are on hold. No cloud topology, provider, or operational service is currently approved.
- If deployment is resumed, four ResilientDB replicas across independent failure domains remain a prerequisite, not a current implementation claim.
- Any future operational logging service may contain operational logs only; all application audit records must remain in ResilientDB.
- Source code and deterministic synthetic test generators live in Git; generated research data and artifacts live only in ResilientDB.
- Failure of a mandatory feasibility gate blocks the affected feature rather than relaxing the sole-database, key-isolation, or signed-settlement constraints.
