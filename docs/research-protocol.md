# Research Protocol

Status: implemented through Milestone 6 for local, non-commercial research

## Scope

Research dataset V1 contains exactly BTC, ETH, and SOL with daily UTC observations from 2020-04-10 through 2025-01-01 inclusive. It combines market, sentiment, and asset-specific on-chain or documented proxy channels. A fourth asset is rejected at ingestion, feature, model, evaluation, portfolio, API, and fixture boundaries.

## Point-in-time data

Every observation records event time, provider availability time, retrieval time, provider revision, request URL or canonical query, response checksum, license/terms reference, and missingness. Joins use the time at which data was available, not a later revised timestamp. Provider failure appends a failed-attempt record and never overwrites a valid observation.

Planned sources:

- Coin Metrics Community: daily market series; daily `AdrActCnt` and `TxCnt` are the pinned V1 BTC/ETH on-chain metric contract.
- CoinGecko: current quote fallback; historical use requires confirmed plan/terms and coverage.
- DefiLlama: documented SOL TVL and stablecoin-supply proxies.
- GDELT: GKG historical tone/coverage and DOC metadata; full copyrighted articles are not persisted.
- `facebook/bart-large-mnli` at the locked revision: supplemental headline classification.

Provider availability differs by asset and date. Missing inputs are explicit masks; values are never silently backfilled from the future. Coin Metrics `PriceUSD` covers all three assets and `AdrActCnt` plus `TxCnt` cover BTC/ETH on every day of the fixed period. DefiLlama Solana TVL begins on 2021-03-17, leaving 341 masked days. Solana USD stablecoin supply begins on 2021-09-10 and contains 243 later gaps, leaving 761 total masked days. Those masks are model inputs; missing observations are not zero values.

## Reproducibility

Every run records:

- Run ID, purpose, owner, UTC start/end, and status.
- Git commit and dirty-state hash.
- Lock-file, code, configuration, environment, dependency-lock, container, dataset, feature, model, prediction, and artifact hashes.
- Exact provider observation IDs and immutable dataset manifest.
- Fixed random seeds for Python, NumPy, framework, data loader, and optimizer.
- CPU/GPU type, operating system, runtime/library versions, deterministic-mode settings, and known nondeterministic operations.
- Chronological train/validation/test windows and every walk-forward fold.
- Metrics, forecast intervals, baseline/ablation results, failures, and promotion decision.

Generated datasets, features, checkpoints, predictions, plots, and manifests are persisted in ResilientDB. Git contains code, deterministic synthetic generators, and small machine-readable acceptance attestations only. Temporary computation files are deleted after verified persistence.

## Evaluation

- Fit transforms on training windows only.
- Calibrate conformal intervals on validation windows only.
- Evaluate naive/zero-return, linear, and sequence baselines.
- Compare market-only, fixed equal fusion, adaptive gating, and each one-source-removed ablation.
- Report point errors, direction metrics, interval coverage/width, portfolio-relevant outcomes, missingness, and uncertainty.
- Do not claim statistical significance without a predeclared test, correction, and adequate sample.
- Label MSPCIFormer work as a three-asset adaptation; do not copy author source until a compatible license or explicit permission is recorded.

## Artifact protocol

Artifacts are compressed, encrypted with AES-256-GCM, split into 256 KiB logical content-addressed chunks, and segmented into transport-safe records under deterministic `blob:{sha256}:...` keys. A manifest records total size, compression, encryption metadata, ordered logical-chunk and transport-segment hashes, aggregate SHA-256, media type, and producing run. Restoration verifies every segment, logical chunk, authenticated envelope, and aggregate digest before use. Schema-v1 unsegmented blobs remain readable.

The local 100 MiB reconstruction smoke test does not satisfy persistence acceptance; the identical round trip must also pass through real ResilientDB and survive restart.

## Milestone 6 implementation note

The checked-in implementation uses pinned NumPy and PyTorch dependencies, CPU-only deterministic algorithms, one framework thread, no random data shuffling, five expanding walk-forward folds, a 15-day embargo, fold-local masked standardization, and validation-only split-conformal calibration. The clean-room MSPCIFormer adaptation uses separate market, sentiment, and on-chain encoders, masked adaptive gating, multi-scale temporal patches, shared channel-independent Transformer processing, learned scale aggregation, asset embeddings, and five-horizon return, direction, and quantile heads.

Synthetic smoke results validate deterministic mechanics, model contracts, comparisons, and persistence. They do not establish real-data performance, statistical significance, financial advice, or promotion eligibility. A full research run must use the fixed point-in-time provider dataset, retain the same manifest contract, and pass the declared promotion criteria before its model can become an approved forecast source.
