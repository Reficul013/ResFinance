# Research Protocol

Status: Milestone 0 baseline

## Scope

Research dataset V1 contains exactly BTC, ETH, and SOL with daily UTC observations from 2020-04-10 through 2025-01-01 inclusive. It combines market, sentiment, and asset-specific on-chain or documented proxy channels. A fourth asset is rejected at ingestion, feature, model, evaluation, portfolio, API, and fixture boundaries.

## Point-in-time data

Every observation records event time, provider availability time, retrieval time, provider revision, request URL or canonical query, response checksum, license/terms reference, and missingness. Joins use the time at which data was available, not a later revised timestamp. Provider failure appends a failed-attempt record and never overwrites a valid observation.

Planned sources:

- Coin Metrics Community: daily market series and available BTC/ETH on-chain metrics.
- CoinGecko: current quote fallback; historical use requires confirmed plan/terms and coverage.
- DefiLlama: documented SOL TVL and stablecoin-supply proxies.
- GDELT: GKG historical tone/coverage and DOC metadata; full copyrighted articles are not persisted.
- `facebook/bart-large-mnli` at the locked revision: supplemental headline classification.

Provider availability differs by asset and date. Missing inputs are explicit masks; values are never silently backfilled from the future. Coin Metrics `PriceUSD` returned all three assets at both fixed-period boundaries. DefiLlama Solana TVL begins after the research start date, so the early proxy interval remains a documented missingness case rather than a value to backfill.

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

Generated datasets, features, checkpoints, predictions, and manifests are persisted in ResilientDB. Git contains code and deterministic synthetic generators only. Temporary computation files are deleted after verified persistence.

## Evaluation

- Fit transforms on training windows only.
- Calibrate conformal intervals on validation windows only.
- Evaluate naive/zero-return, linear, and sequence baselines.
- Compare market-only, fixed equal fusion, adaptive gating, and each one-source-removed ablation.
- Report point errors, direction metrics, interval coverage/width, portfolio-relevant outcomes, missingness, and uncertainty.
- Do not claim statistical significance without a predeclared test, correction, and adequate sample.
- Label MSPCIFormer work as a three-asset adaptation; do not copy author source until a compatible license or explicit permission is recorded.

## Artifact protocol

Artifacts are compressed, split into 256 KiB content-addressed chunks, and written to deterministic `blob:{sha256}:{chunk_number}` keys. A manifest records total size, compression, ordered chunk hashes, aggregate SHA-256, media type, and producing run. Restoration verifies every chunk and the aggregate digest before use.

The local 100 MiB reconstruction smoke test does not satisfy persistence acceptance; the identical round trip must also pass through real ResilientDB and survive restart.
