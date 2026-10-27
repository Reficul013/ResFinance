from __future__ import annotations

import argparse
import hashlib
import json
import os
import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast

from torch import Tensor

from ml.data.datasets import HORIZONS
from ml.features.point_in_time import FeatureDataset, PointInTimeFeatureBuilder
from ml.models.mspciformer import FusionMode, ThreeAssetMSPCIFormer
from ml.runs.checkpoints import restore_checkpoint
from ml.runs.forward import (
    ForwardResearchResult,
    ForwardRunConfig,
    infer_current_forecast,
    run_forward_research,
    standardizer_from_artifact,
)
from scripts.milestone9.run_full_research import load_research_key
from server.app.application.crypto_ingestion import CryptoIngestionService
from server.app.domain.crypto import CryptoAsset
from server.app.domain.portfolio import AssetForecast, ForecastSnapshot, PricePoint
from server.app.infrastructure.blob_repository import EncryptedBlobRepository
from server.app.infrastructure.crypto_repository import CryptoResearchRepository
from server.app.infrastructure.encryption import AesGcmCipher
from server.app.infrastructure.portfolio_repository import PortfolioResearchRepository
from server.app.infrastructure.provider_adapters import (
    CoinMetricsMarketAdapter,
    CoinMetricsOnChainAdapter,
    DefiLlamaSolanaAdapter,
)
from server.app.infrastructure.research_repository import PromotionCriteria, ResearchRunRepository
from server.app.infrastructure.resilientdb_cli import DockerResilientDBEventStore

START = date(2020, 4, 10)
FORWARD_START = date(2025, 1, 2)
PROVIDERS = ("coin-metrics", "defillama", "gdelt")


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description=(
            "Run the predeclared Milestone 9 untouched-forward protocol, promote only on "
            "the immutable gate, and publish a current-cutoff forecast snapshot."
        )
    )
    value.add_argument("--docker", type=Path, default=Path("docker"))
    value.add_argument("--docker-host")
    value.add_argument("--container", default="resfinance-resdb-tools")
    value.add_argument("--config", default="/config/client.config")
    value.add_argument(
        "--current-cutoff-date",
        type=date.fromisoformat,
        default=date.today() - timedelta(days=1),
    )
    value.add_argument("--epochs", type=int, default=20)
    value.add_argument("--approved-by", default="resfinance-local-research")
    value.add_argument("--encryption-key-env", default="RESFINANCE_RESEARCH_ENCRYPTION_KEY")
    value.add_argument("--encryption-key-container", default="resfinance-api-1")
    value.add_argument("--encryption-key-path", default="/certs/research-blob.key")
    value.add_argument("--output", type=Path, required=True)
    return value


def main() -> int:
    args = parser().parse_args()
    if args.epochs < 1:
        raise ValueError("epochs must be positive")
    if args.current_cutoff_date < date(2025, 4, 17):
        raise ValueError("current cutoff cannot produce the predeclared forward holdout")
    environment_key = os.environ.get(args.encryption_key_env)
    key = load_research_key(
        variable=args.encryption_key_env,
        docker=args.docker,
        docker_host=args.docker_host,
        container=args.encryption_key_container,
        path=args.encryption_key_path,
    )
    store = DockerResilientDBEventStore(
        docker=args.docker,
        docker_host=args.docker_host,
        container=args.container,
        config_path=args.config,
        timeout_seconds=120,
    )
    crypto = CryptoResearchRepository(store)
    receipts = ingest_forward(crypto, end=args.current_cutoff_date)
    dataset = build_current_dataset(crypto, end=args.current_cutoff_date)
    crypto.put_feature_dataset_archive(
        dataset_hash=dataset.dataset_hash,
        rows=dataset.rows,
        manifest=dataset.manifest,
    )
    result = run_forward_research(
        dataset,
        config=ForwardRunConfig(epochs=args.epochs),
    )
    repository = ResearchRunRepository(
        store,
        EncryptedBlobRepository(
            store,
            AesGcmCipher(
                key,
                key_id=(
                    "local-research-blob-key-v1"
                    if environment_key is None
                    else "local-research-override-" + hashlib.sha256(key).hexdigest()[:16]
                ),
            ),
        ),
    )
    persisted = repository.put_completed_run(result.manifest, result.artifacts)
    metrics = cast(dict[str, dict[str, object]], result.manifest["metrics"])
    evidence: dict[str, object] = {
        "schema_version": 1,
        "completed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "scope": "milestone-9-forward-completion-on-real-resilientdb",
        "persistent_database": "Apache ResilientDB LevelDB backend",
        "assets": [asset.value for asset in CryptoAsset],
        "providers": list(PROVIDERS),
        "provider_receipts": receipts,
        "current_cutoff_date": args.current_cutoff_date.isoformat(),
        "dataset_hash": dataset.dataset_hash,
        "dataset_row_count": len(dataset.rows),
        "run_id": result.run_id,
        "manifest_key": persisted.manifest_key,
        "evaluation_protocol": result.manifest["evaluation_protocol"],
        "forward_holdout": result.manifest["forward_holdout"],
        "adaptive_calibration": result.manifest["adaptive_calibration"],
        "adaptive_metrics": metrics["adaptive-gating"],
        "naive_metrics": metrics["naive-zero-return"],
        "promotion_criteria": dict(PromotionCriteria().__dict__),
        "statistical_significance_claim": None,
        "three_asset_adaptation": True,
        "author_repository_code_copied": False,
    }
    try:
        promotion = repository.promote_model(
            run_id=result.run_id,
            model_name=FusionMode.ADAPTIVE.value,
            criteria=PromotionCriteria(),
            promoted_at_utc=datetime.now(UTC),
            approved_by=args.approved_by,
        )
    except ValueError as exc:
        evidence.update(
            {
                "promotion_event_id": None,
                "promotion_rejected": True,
                "promotion_reason": str(exc),
                "live_forecast_snapshot_published": False,
            }
        )
        _write_evidence(args.output, evidence)
        return 2
    promotion_event_id = promotion.key.removeprefix("promotion:forecast:")
    snapshot, fallback_assets = make_snapshot(
        dataset,
        result=result,
        promotion_event_id=promotion_event_id,
    )
    snapshot_receipt = PortfolioResearchRepository(store, repository).put_forecast_snapshot(
        snapshot
    )
    evidence.update(
        {
            "promotion_event_id": promotion_event_id,
            "promotion_rejected": False,
            "deployment_model_hash": snapshot.model_hash,
            "forecast_snapshot_id": snapshot.snapshot_id,
            "forecast_snapshot_record_id": snapshot_receipt.record_id,
            "forecast_as_of_utc": snapshot.as_of_utc.isoformat().replace("+00:00", "Z"),
            "forecast_expires_at_utc": snapshot.expires_at_utc.isoformat().replace("+00:00", "Z"),
            "forecast_horizon_days": snapshot.horizon_days,
            "forecast_policy": result.manifest["forecast_policy"],
            "forecast_market_only_fallback_assets": list(fallback_assets),
            "live_forecast_snapshot_published": True,
        }
    )
    _write_evidence(args.output, evidence)
    return 0


def ingest_forward(repository: CryptoResearchRepository, *, end: date) -> list[dict[str, object]]:
    service = CryptoIngestionService(repository)
    started = datetime.combine(FORWARD_START, time.min, tzinfo=UTC)
    completed = datetime.combine(end, time.max, tzinfo=UTC)
    identifier = uuid.uuid4().hex
    adapters = (
        CoinMetricsMarketAdapter(),
        CoinMetricsOnChainAdapter(),
        DefiLlamaSolanaAdapter(),
    )
    receipts: list[dict[str, object]] = []
    for adapter in adapters:
        assets = tuple(asset for asset in CryptoAsset if asset in adapter.supported_assets)
        receipt = service.ingest_archived(
            adapter,
            assets=assets,
            start_utc=started,
            end_utc=completed,
            attempt_id=f"milestone9-forward-{identifier}-{adapter.adapter_id}",
        )
        receipts.append(dict(receipt.__dict__))
    return receipts


def build_current_dataset(repository: CryptoResearchRepository, *, end: date) -> FeatureDataset:
    as_of = datetime.combine(end + timedelta(days=1), time.max, tzinfo=UTC)
    observations = repository.observations()
    dataset = PointInTimeFeatureBuilder().build(
        observations,
        assets=tuple(CryptoAsset),
        providers=PROVIDERS,
        start=START,
        end=end,
        as_of_utc=as_of,
    )
    latest_rows = [row for row in dataset.rows if str(row["timestamp_utc"])[:10] == end.isoformat()]
    if len(latest_rows) != 3:
        raise ValueError("current feature cutoff must contain exactly BTC, ETH, and SOL")
    for row in latest_rows:
        values = cast(dict[str, object], row["values"])
        masks = cast(dict[str, object], row["availability_masks"])
        if masks.get("market_price_usd") is not True or values.get("market_price_usd") is None:
            raise ValueError("current cutoff is missing a point-in-time market price")
        decision = datetime.fromisoformat(str(row["decision_time_utc"]).replace("Z", "+00:00"))
        provenance = cast(dict[str, str], row["source_record_ids"])
        price_record_id = provenance["market_price_usd"]
        matching = [item for item in observations if item.record_id == price_record_id]
        if len(matching) != 1 or matching[0].available_at_utc > decision:
            raise ValueError("current feature violates available_at point-in-time enforcement")
    return dataset


def make_snapshot(
    dataset: FeatureDataset,
    *,
    result: ForwardResearchResult,
    promotion_event_id: str,
) -> tuple[ForecastSnapshot, tuple[str, ...]]:
    manifest = result.manifest
    artifacts = result.artifacts
    model_artifact = str(manifest["deployment_model_artifact"])
    checkpoint = artifacts[model_artifact]
    model = ThreeAssetMSPCIFormer(fusion_mode=FusionMode.ADAPTIVE)
    model_hash = restore_checkpoint(model, checkpoint)
    standardizer = standardizer_from_artifact(artifacts[str(manifest["standardizer_artifact"])])
    calibration = cast(dict[str, object], manifest["adaptive_calibration"])
    fallback_model = None
    fallback_artifact = manifest.get("fallback_model_artifact")
    if fallback_artifact:
        fallback_model = ThreeAssetMSPCIFormer(fusion_mode=FusionMode.MARKET_ONLY)
        restore_checkpoint(fallback_model, artifacts[str(fallback_artifact)])
    current = infer_current_forecast(
        dataset,
        model=model,
        standardizer=standardizer,
        calibration=calibration,
        fallback_model=fallback_model,
    )
    assets = (CryptoAsset.BTC, CryptoAsset.ETH, CryptoAsset.SOL)
    horizon_index = HORIZONS.index(15)
    forecasts = tuple(
        AssetForecast(
            asset=asset,
            expected_return=_decimal(current.expected[index, horizon_index]),
            probability_up=_decimal(current.probability_up[index, horizon_index]),
            p10_return=_decimal(current.p10[index, horizon_index]),
            p50_return=_decimal(current.p50[index, horizon_index]),
            p90_return=_decimal(current.p90[index, horizon_index]),
        )
        for index, asset in enumerate(assets)
    )
    price_history = _price_history(dataset, days=60)
    as_of = datetime.fromisoformat(current.decision_time_utc.replace("Z", "+00:00"))
    snapshot = ForecastSnapshot(
        as_of_utc=as_of,
        expires_at_utc=as_of + timedelta(days=2),
        horizon_days=15,
        run_id=result.run_id,
        model_name="adaptive-gating",
        model_hash=model_hash,
        dataset_hash=result.dataset_hash,
        promotion_event_id=promotion_event_id,
        forecasts=forecasts,
        price_history=price_history,
    )
    fallback_assets = tuple(
        asset.value for asset, used in zip(assets, current.fallback_used, strict=True) if used
    )
    return snapshot, fallback_assets


def _price_history(dataset: FeatureDataset, *, days: int) -> tuple[PricePoint, ...]:
    by_asset: dict[CryptoAsset, list[dict[str, object]]] = {asset: [] for asset in CryptoAsset}
    for row in dataset.rows:
        values = cast(dict[str, object], row["values"])
        masks = cast(dict[str, object], row["availability_masks"])
        if masks.get("market_price_usd") is True and values.get("market_price_usd") is not None:
            by_asset[CryptoAsset.parse(str(row["asset"]))].append(row)
    points: list[PricePoint] = []
    for asset in CryptoAsset:
        rows = sorted(by_asset[asset], key=lambda row: str(row["timestamp_utc"]))[-days:]
        if len(rows) < 3:
            raise ValueError("forecast snapshot requires at least three price observations")
        for row in rows:
            values = cast(dict[str, object], row["values"])
            provenance = cast(dict[str, str], row["source_record_ids"])
            points.append(
                PricePoint(
                    asset=asset,
                    observed_at_utc=datetime.fromisoformat(
                        str(row["timestamp_utc"]).replace("Z", "+00:00")
                    ),
                    price_usd=str(values["market_price_usd"]),
                    source_record_id=provenance["market_price_usd"],
                )
            )
    return tuple(points)


def _decimal(value: Tensor) -> str:
    parsed = Decimal(str(float(value)))
    if parsed == 0:
        return "0"
    return format(parsed.normalize(), "f")


def _write_evidence(path: Path, evidence: dict[str, object]) -> None:
    rendered = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    raise SystemExit(main())
