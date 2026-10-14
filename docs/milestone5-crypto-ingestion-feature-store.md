# Milestone 5 Crypto Ingestion and Feature Store

Status: complete for local, non-commercial research. Cloud, production, institutional, and commercial use remain on hold.

## Purpose

Milestone 5 turns the Milestone 0 provider feasibility evidence into an application-owned ingestion and feature-store boundary. It collects only BTC, ETH, and SOL research signals, preserves exactly what was known and when it was available, and stores the resulting observations and derived feature datasets in Apache ResilientDB without introducing another persistent database.

Forecast training, MSPCIFormer, Adaptive Multi-Source Gating, walk-forward evaluation, and model promotion remain Milestone 6 work.

## Implemented provider adapters

- **Coin Metrics Community:** daily BTC/ETH/SOL `PriceUSD` plus daily BTC/ETH `AdrActCnt` and `TxCnt`, including pagination, decimal-string preservation, response hashes, source queries, and the recorded CC BY-NC 4.0 research disposition.
- **CoinGecko:** current BTC/ETH/SOL USD quote fallback with provider timestamps and attribution metadata. It is not used as the historical research source.
- **DefiLlama:** daily Solana TVL and USD stablecoin-supply proxies. The adapter emits one record per requested day and metric, including explicit null/missing observations; unavailable history is never converted to zero.
- **GDELT:** strict ingestion of the bounded daily GKG aggregate CSV produced by the approved BigQuery query. It persists counts and average tone, not full copyrighted article text.

The live adapter smoke on 2026-10-14 successfully parsed Coin Metrics market and on-chain responses, DefiLlama Solana proxy responses, and current CoinGecko quotes for all three assets.

## Immutable ResilientDB records

The repository stores:

- Raw market, on-chain, and sentiment observations under deterministic `mkt:`, `chain:`, and `sent:` keys.
- Event time, conservative provider-availability time, first retrieval time, provider/revision, source reference, interval, decimal value or explicit missingness, response SHA-256, terms reference, and license disposition.
- Immutable provider-license records.
- Append-only success/failure ingestion-attempt records with error digests rather than raw provider exception content.
- Derived feature rows under content-addressed `feat:{dataset_hash}:...` keys.
- Dataset manifests containing the fixed schema, asset list, point-in-time cutoff, decision lag, row checksum, source observation IDs, and dataset hash.

An unchanged observation fetched later deduplicates against its stable source identity while preserving its original retrieval evidence. A changed observation cannot overwrite the same provider revision; a provider correction must use a distinct revision.

## Point-in-time feature construction

The feature builder creates a daily UTC grid with:

- Market price and one-day return.
- GDELT average tone and document counts.
- BTC/ETH active-address and transaction-count metrics.
- SOL TVL and stablecoin-supply proxy metrics.
- A mask for every feature plus market, sentiment, and on-chain source masks.
- Exact source observation IDs for every populated feature.
- An explicit provider allowlist in each manifest, so acceptance/synthetic records cannot enter a live research dataset merely because they share a date and metric.

For each date, the builder selects only a revision whose provider-availability time is at or before that date's decision cutoff. A later revision is excluded even when it exists in ResilientDB. Preprocessing and model fitting are deliberately absent from this milestone.

## Acceptance evidence

The deterministic acceptance writes synthetic provider observations and feature rows through the pinned local ResilientDB client into the running four-replica stack. Synthetic data is used so the acceptance result does not depend on provider availability and does not commit generated research data to Git.

The recorded run in [`config/milestone5-local-attestation.json`](../config/milestone5-local-attestation.json) passed:

- Exactly `BTC | ETH | SOL`; `DOGE` was rejected before provider or persistence work.
- 28 immutable raw observations inserted into real ResilientDB.
- All 28 observations deduplicated on repeat ingestion.
- An injected provider failure appended a failed-attempt record and left the observation count unchanged.
- Nine daily point-in-time feature rows plus one dataset manifest persisted.
- Every feature row and the manifest deduplicated on repeat persistence.
- A future-available BTC revision was excluded from the earlier feature row.
- Missing SOL TVL remained null with a false mask, never numeric zero.

Automated verification on 2026-10-14:

- Ruff passed.
- Mypy passed across the configured Milestone 0–3 and Milestone 5 scripts, backend, ML feature code, blockchain adapters, and wallet helpers.
- Pytest passed all 72 tests with one pre-existing Starlette `TestClient` deprecation warning.
- The live provider adapter smoke passed.
- The real ResilientDB Milestone 5 acceptance passed.

Run the acceptance with:

```bash
docker compose --profile tools up -d --build --wait \
  resdb-1 resdb-2 resdb-3 resdb-4 resdb-proxy resdb-tools
.venv/bin/python -m scripts.milestone5.run_crypto_ingestion_acceptance \
  --docker "$(command -v docker)" \
  --output config/milestone5-local-attestation.json
```

## Boundaries and next milestone

- Provider permission remains limited to the dispositions in [`provider-terms-review.md`](provider-terms-review.md). Technical availability does not approve commercial or institutional use.
- The fixed historical research boundary remains 2020-04-10 through 2025-01-01 inclusive.
- GDELT historical aggregates still come from the bounded, validated BigQuery export; the DOC API remains a near-term metadata source rather than a substitute historical dataset.
- No generated provider payload, dataset, or feature artifact is committed to Git.
- This milestone does not claim production ingestion reliability or cloud/BFT readiness.

Milestone 6 may now implement deterministic synthetic smoke datasets, baselines, the documented three-asset MSPCIFormer adaptation, Adaptive Multi-Source Gating, chronological walk-forward evaluation, conformal intervals, ablations, and complete research-run manifests.
