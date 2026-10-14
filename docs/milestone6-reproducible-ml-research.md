# Milestone 6 Reproducible ML Research

Status: complete for local research mechanics and deterministic synthetic acceptance. No model is promoted, and cloud, production, commercial, institutional, trading, and investment-advice uses remain out of scope.

## Purpose

Milestone 6 turns the point-in-time feature datasets from Milestone 5 into an auditable forecasting research system. It implements the declared models, chronological evaluation, uncertainty calibration, ablations, immutable run records, encrypted model artifacts, and explicit promotion controls without copying code from the unlicensed MSPCIFormer author repository.

The deterministic synthetic smoke dataset validates mechanics and reproducibility only. It is not evidence that a model will perform well on the fixed historical provider dataset or future markets.

## Implemented models

- A last-value/zero-return naive baseline.
- A closed-form ridge-linear baseline.
- An LSTM sequence baseline.
- A clean-room three-asset MSPCIFormer adaptation with:
  - separate market, sentiment, and on-chain encoders;
  - explicit feature and source masks;
  - per-asset, per-time-step masked Adaptive Multi-Source Gating;
  - temporal patch sizes of 2, 4, and 8 days;
  - channel-independent Transformer processing with shared weights;
  - learned aggregation across patch scales;
  - asset embeddings for exactly BTC, ETH, and SOL;
  - expected-return, direction-probability, and p10/p50/p90 heads for 1-, 3-, 5-, 7-, and 15-day horizons.

Required comparisons execute under one forecast contract: market-only, fixed equal fusion, adaptive gating, without-market, without-sentiment, and without-on-chain. A fourth asset is rejected before model construction.

## Evaluation protocol

- Five expanding chronological walk-forward folds.
- A 15-day embargo between train/validation and validation/test windows.
- No random shuffling.
- Masked standardization fit independently on each training window.
- Split-conformal calibration using validation residuals only.
- MAE, RMSE, directional accuracy, Brier score, interval coverage, interval width, annualized Sharpe, maximum drawdown, and 0/10/25-basis-point transaction-cost sensitivity.
- Descriptive baseline and ablation reporting only; no statistical-significance claim is made.

## Reproducibility and provenance

Every completed run records its purpose, owner, UTC timing, parent run, Git commit and dirty-state hash, ML code hash, complete pinned dependency lock and hash, configuration and hash, source record IDs, dataset and feature-manifest hashes, fold boundaries, preprocessing, seeds, deterministic flags, hardware/runtime details, model hashes, prediction hash, metrics, gate weights, warnings, and artifact hashes.

CPU smoke execution pins Python 3.13, NumPy 2.5.4, and PyTorch 2.14.1, uses one framework thread, enables deterministic algorithms, seeds Python/NumPy/PyTorch/data-loader/optimizer paths, and performs no random data shuffling. The acceptance criterion is repeatability on the same platform and dependency set; PyTorch does not guarantee bit-identical results across different releases or platforms.

## ResilientDB artifact persistence

Research manifests use deterministic `run:{run_id}:manifest` keys. Checkpoints use a deterministic JSON tensor encoding rather than a timestamp-bearing archive. Predictions, metrics, gate-weight reports, the walk-forward MAE SVG, and all fold/model checkpoints are hashed, compressed, AES-256-GCM encrypted, and persisted through the existing ResilientDB blob repository.

The repository retains 256 KiB logical chunks and now segments each logical chunk into CLI-safe transport records. Restoration supports both the new segmented schema and existing schema-v1 blobs, and verifies transport-segment hashes, logical-chunk hashes, authenticated encryption, size, and aggregate content hash.

## Promotion control

Only a completed adaptive-gating run with all required comparisons and artifacts can be promoted. The default `forecast-promotion-v1` criteria require adaptive MAE no worse than the naive baseline and interval coverage of at least 70 percent. A successful promotion appends an immutable event containing the criteria version, evaluated metrics, checks, approver, run ID, and model name. Failed criteria raise an error and do not create a promotion event.

The deterministic smoke candidate was not promoted. Its adaptive MAE was `0.0483409762`, compared with naive MAE `0.0224560387`; the declared MAE criterion therefore rejected it. This is the correct research outcome, not an acceptance failure: the milestone proves the evaluation and governance pipeline, not model superiority on synthetic data.

## Acceptance evidence

The local acceptance ran twice on CPU and then persisted both complete runs through the real four-replica Apache ResilientDB stack:

- Dataset SHA-256: `2c11ce17e3a80f9efe84b579dc1ff9c533de24d19b2da2b32be1cf50266d576d`.
- Prediction SHA-256: `c80a13add27f3685a257a2ffcf666536e9d90baf1e728e27a7b3ce2d67cf97f3`.
- Both hashes were identical across repeated CPU runs.
- All five chronological folds and all nine required model/baseline/ablation variants were reported.
- All 39 artifacts were restored byte-for-byte from ResilientDB.
- Repeating the same run persistence deduplicated cleanly.
- The promotion gate rejected the adaptive candidate because its MAE did not beat the naive baseline.
- No author-repository source was copied.

The machine-readable final run is checked in as `config/milestone6-local-attestation.json`. The preliminary values above are deterministic and are rechecked after the implementation commit before the attestation is recorded.

## Verification

```bash
.venv/bin/ruff check .
.venv/bin/mypy
.venv/bin/pytest

docker compose --profile tools up -d --build --wait \
  resdb-1 resdb-2 resdb-3 resdb-4 resdb-proxy resdb-tools
.venv/bin/python -m scripts.milestone6.run_ml_acceptance \
  --docker "$(command -v docker)" \
  --output config/milestone6-local-attestation.json
```

## Boundaries and next milestone

- Generated datasets, checkpoints, predictions, metrics, plots, and run manifests stay in ResilientDB; Git contains only code, the deterministic generator, documentation, and the small acceptance attestation.
- The synthetic acceptance run does not replace a full point-in-time provider-data research run.
- A model is not an approved forecast source until a full run passes explicit promotion criteria and appends an immutable promotion event.
- Model output is research analysis, not financial advice, and no path trades or mutates Finance.
- No cloud or production readiness is claimed.

Milestone 7 may now implement risk scoring, constrained BTC/ETH/SOL portfolio optimization, forecast presentation, and non-mutating amount scenarios against the immutable forecast/run interfaces. It must reject stale or unpromoted forecasts and may not treat the rejected synthetic smoke candidate as an approved model.
