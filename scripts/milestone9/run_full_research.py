from __future__ import annotations

import argparse
import hashlib
import json
import os
import uuid
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import cast

from ml.features.point_in_time import FeatureDataset, PointInTimeFeatureBuilder
from ml.runs.runner import SmokeRunConfig, run_smoke_research
from server.app.application.crypto_ingestion import CryptoIngestionService
from server.app.domain.crypto import CryptoAsset
from server.app.infrastructure.blob_repository import EncryptedBlobRepository
from server.app.infrastructure.crypto_repository import CryptoResearchRepository
from server.app.infrastructure.encryption import AesGcmCipher
from server.app.infrastructure.provider_adapters import (
    CoinMetricsMarketAdapter,
    CoinMetricsOnChainAdapter,
    DefiLlamaSolanaAdapter,
    GdeltGkgCsvAdapter,
)
from server.app.infrastructure.research_repository import (
    PromotionCriteria,
    ResearchRunRepository,
)
from server.app.infrastructure.resilientdb_cli import DockerResilientDBEventStore

FIXED_START = date(2020, 4, 10)
FIXED_END = date(2025, 1, 1)
PROVIDERS = ("coin-metrics", "defillama", "gdelt")


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description=(
            "Run the approved non-smoke BTC/ETH/SOL protocol and apply the immutable "
            "forecast-promotion-v1 gate."
        )
    )
    value.add_argument("--docker", type=Path, default=Path("docker"))
    value.add_argument("--docker-host")
    value.add_argument("--container", default="resfinance-resdb-tools")
    value.add_argument("--config", default="/config/client.config")
    value.add_argument("--dataset-hash")
    value.add_argument("--ingest", action="store_true")
    value.add_argument("--gdelt-csv", type=Path)
    value.add_argument("--epochs", type=int, default=20)
    value.add_argument("--approved-by", default="resfinance-local-research")
    value.add_argument(
        "--encryption-key-env",
        default="RESFINANCE_RESEARCH_ENCRYPTION_KEY",
        help="environment variable containing a 32-byte hexadecimal artifact key",
    )
    value.add_argument("--output", type=Path, required=True)
    return value


def main() -> int:
    args = parser().parse_args()
    if args.epochs < 1:
        raise ValueError("epochs must be positive")
    if args.ingest == bool(args.dataset_hash):
        raise ValueError("choose exactly one of --ingest or --dataset-hash")
    if args.ingest and args.gdelt_csv is None:
        raise ValueError("--ingest requires the approved daily --gdelt-csv export")
    key = load_encryption_key(args.encryption_key_env)

    store = DockerResilientDBEventStore(
        docker=args.docker,
        docker_host=args.docker_host,
        container=args.container,
        config_path=args.config,
        timeout_seconds=120,
    )
    crypto = CryptoResearchRepository(store)
    dataset = (
        ingest_and_build(crypto, args.gdelt_csv)
        if args.ingest
        else load_dataset(crypto, str(args.dataset_hash))
    )
    unique_dates = len({str(row["timestamp_utc"])[:10] for row in dataset.rows})
    validation_dates = 60
    test_dates = 30
    minimum_train_dates = unique_dates - validation_dates - 5 * test_dates - 30
    if minimum_train_dates < 365:
        raise ValueError("full research dataset must provide at least one year of training history")

    run_id = f"milestone9-{uuid.uuid4().hex}"
    config = SmokeRunConfig(
        epochs=args.epochs,
        minimum_train_dates=minimum_train_dates,
        validation_dates=validation_dates,
        test_dates=test_dates,
        purpose="milestone-9-full-provider-research",
        owner="resfinance-local-research",
    )
    result = run_smoke_research(dataset, config=config, run_id=run_id)
    key_id = f"milestone9-local-research-{hashlib.sha256(key).hexdigest()[:12]}"
    repository = ResearchRunRepository(
        store,
        EncryptedBlobRepository(
            store,
            AesGcmCipher(key, key_id=key_id),
        ),
    )
    persisted = repository.put_completed_run(result.manifest, result.artifacts)
    promotion_event_id: str | None = None
    promotion_reason: str | None = None
    try:
        promotion = repository.promote_model(
            run_id=result.run_id,
            model_name="adaptive-gating",
            criteria=PromotionCriteria(),
            promoted_at_utc=datetime.now(UTC),
            approved_by=args.approved_by,
        )
        promotion_event_id = promotion.key.removeprefix("promotion:forecast:")
    except ValueError as exc:
        promotion_reason = str(exc)

    metrics = cast(dict[str, object], result.manifest["metrics"])
    evidence = {
        "schema_version": 1,
        "completed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "scope": "local-full-provider-research-on-real-resilientdb",
        "persistent_database": "Apache ResilientDB LevelDB backend",
        "assets": [asset.value for asset in CryptoAsset],
        "fixed_period": {"start": FIXED_START.isoformat(), "end": FIXED_END.isoformat()},
        "providers": list(PROVIDERS),
        "dataset_hash": dataset.dataset_hash,
        "dataset_row_count": len(dataset.rows),
        "run_id": result.run_id,
        "manifest_key": persisted.manifest_key,
        "artifact_count": len(result.artifacts),
        "artifact_hashes": result.manifest["artifact_hashes"],
        "folds": result.manifest["folds"],
        "reported_models": result.manifest["reported_models"],
        "required_comparisons_complete": result.manifest[
            "required_comparisons_complete"
        ],
        "adaptive_metrics": metrics["adaptive-gating"],
        "naive_metrics": metrics["naive-zero-return"],
        "promotion_criteria": dict(PromotionCriteria().__dict__),
        "promotion_event_id": promotion_event_id,
        "promotion_rejected": promotion_event_id is None,
        "promotion_reason": promotion_reason,
        "live_forecast_snapshot_published": False,
        "live_forecast_note": (
            "No snapshot is published from held-out evaluation predictions. A normal runtime "
            "forecast requires a separately implemented current-cutoff inference artifact."
            if promotion_event_id is not None
            else "No snapshot may be published without an eligible promotion event."
        ),
        "statistical_significance_claim": None,
        "three_asset_adaptation": True,
        "author_repository_code_copied": False,
    }
    rendered = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if promotion_event_id is not None else 2


def ingest_and_build(
    repository: CryptoResearchRepository,
    gdelt_csv: Path | None,
) -> FeatureDataset:
    if gdelt_csv is None or not gdelt_csv.is_file():
        raise FileNotFoundError("approved GDELT aggregate CSV is missing")
    service = CryptoIngestionService(repository)
    start = datetime.combine(FIXED_START, time.min, tzinfo=UTC)
    end = datetime.combine(FIXED_END, time.max, tzinfo=UTC)
    run_id = uuid.uuid4().hex
    providers = (
        CoinMetricsMarketAdapter(),
        CoinMetricsOnChainAdapter(),
        DefiLlamaSolanaAdapter(),
        GdeltGkgCsvAdapter(
            gdelt_csv,
            source_reference="local-approved-gdelt-bigquery-aggregate",
        ),
    )
    for provider in providers:
        assets = tuple(asset for asset in CryptoAsset if asset in provider.supported_assets)
        service.ingest(
            provider,
            assets=assets,
            start_utc=start,
            end_utc=end,
            attempt_id=f"milestone9-{run_id}-{provider.adapter_id}",
        )
    dataset = PointInTimeFeatureBuilder().build(
        repository.observations(),
        assets=tuple(CryptoAsset),
        providers=PROVIDERS,
        start=FIXED_START,
        end=FIXED_END,
        as_of_utc=datetime.now(UTC),
    )
    repository.put_feature_dataset(
        dataset_hash=dataset.dataset_hash,
        rows=dataset.rows,
        manifest=dataset.manifest,
    )
    return dataset


def load_encryption_key(variable: str) -> bytes:
    encoded = os.environ.get(variable)
    if encoded is None:
        raise ValueError(f"{variable} must contain a 32-byte hexadecimal key")
    try:
        key = bytes.fromhex(encoded)
    except ValueError as exc:
        raise ValueError(f"{variable} must contain a 32-byte hexadecimal key") from exc
    if len(key) != 32:
        raise ValueError(f"{variable} must contain a 32-byte hexadecimal key")
    return key


def load_dataset(repository: CryptoResearchRepository, dataset_hash: str) -> FeatureDataset:
    manifest = repository.dataset_manifest(dataset_hash)
    rows = repository.feature_rows(dataset_hash)
    return FeatureDataset(dataset_hash, tuple(rows), manifest)


if __name__ == "__main__":
    raise SystemExit(main())
