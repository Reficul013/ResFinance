from __future__ import annotations

import argparse
import hashlib
import json
import os
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import cast

from ml.evaluation.prospective import gate_decision, ledger_entry, score_ledger
from ml.features.point_in_time import FeatureDataset
from ml.models.mspciformer import FusionMode, ThreeAssetMSPCIFormer
from ml.runs.checkpoints import restore_models
from ml.runs.forward import (
    ForwardResearchResult,
    ProspectiveRunConfig,
    infer_current_forecast,
    run_forward_research,
    standardizer_from_artifact,
)
from scripts.milestone9.run_forward_completion import build_current_dataset, make_snapshot
from scripts.milestone9.run_full_research import load_research_key
from server.app.application.crypto_ingestion import CryptoIngestionService
from server.app.application.providers import CryptoDataProvider
from server.app.domain.crypto import CryptoAsset, ObservationChannel, ProviderObservation
from server.app.infrastructure.blob_repository import EncryptedBlobRepository
from server.app.infrastructure.crypto_repository import CryptoResearchRepository
from server.app.infrastructure.encryption import AesGcmCipher
from server.app.infrastructure.portfolio_repository import PortfolioResearchRepository
from server.app.infrastructure.prospective_repository import ProspectiveLedgerRepository
from server.app.infrastructure.provider_adapters import (
    CoinMetricsMarketAdapter,
    CoinMetricsOnChainAdapter,
    DefiLlamaSolanaAdapter,
    GdeltDocTimelineAdapter,
)
from server.app.infrastructure.research_repository import ResearchRunRepository
from server.app.infrastructure.resilientdb_cli import DockerResilientDBEventStore

START = date(2020, 4, 10)
PROVIDERS = ("coin-metrics", "defillama", "gdelt-doc")
# Each adapter resumes from the newest day it has stored for its provider and channel.
INGESTION: tuple[tuple[Callable[[], CryptoDataProvider], str, ObservationChannel], ...] = (
    (CoinMetricsMarketAdapter, "coin-metrics", ObservationChannel.MARKET),
    (CoinMetricsOnChainAdapter, "coin-metrics", ObservationChannel.ON_CHAIN),
    (DefiLlamaSolanaAdapter, "defillama", ObservationChannel.ON_CHAIN),
    (GdeltDocTimelineAdapter, "gdelt-doc", ObservationChannel.SENTIMENT),
)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description=(
            "Protocol v3: ingest provider data, freeze the predeclared run, record one "
            "prospective forecast per day, score matured forecasts, and promote only from a "
            "passing prospective gate."
        )
    )
    commands = value.add_subparsers(dest="command", required=True)
    for name in ("ingest", "freeze", "issue", "score", "promote"):
        command = commands.add_parser(name)
        command.add_argument("--docker", type=Path, default=Path("docker"))
        command.add_argument("--docker-host")
        command.add_argument("--container", default="resfinance-resdb-tools")
        command.add_argument("--config", default="/config/client.config")
        command.add_argument("--encryption-key-env", default="RESFINANCE_RESEARCH_ENCRYPTION_KEY")
        command.add_argument("--encryption-key-container", default="resfinance-api-1")
        command.add_argument("--encryption-key-path", default="/certs/research-blob.key")
        command.add_argument("--output", type=Path)
        if name in ("issue", "score", "promote"):
            command.add_argument("--run-id", required=True)
    commands.choices["freeze"].add_argument(
        "--epochs", type=int, default=ProspectiveRunConfig().epochs
    )
    commands.choices["promote"].add_argument("--approved-by", required=True)
    return value


def main() -> int:
    args = parser().parse_args()
    store = DockerResilientDBEventStore(
        docker=args.docker,
        docker_host=args.docker_host,
        container=args.container,
        config_path=args.config,
        timeout_seconds=120,
    )
    crypto = CryptoResearchRepository(store)
    yesterday = datetime.now(UTC).date() - timedelta(days=1)
    if args.command == "ingest":
        return _report(args.output, {"ingestion": ingest_latest(crypto, end=yesterday)})
    research = _research_repository(store, args)
    ledger = ProspectiveLedgerRepository(store, research)
    if args.command == "freeze":
        return freeze(crypto, research, end=yesterday, epochs=args.epochs, output=args.output)
    if args.command == "issue":
        return issue(crypto, research, ledger, run_id=args.run_id, output=args.output)
    if args.command == "score":
        return score(crypto, ledger, run_id=args.run_id, output=args.output)
    promotion = research.promote_prospective(
        run_id=args.run_id, promoted_at_utc=datetime.now(UTC), approved_by=args.approved_by
    )
    dataset = build_current_dataset(crypto, end=yesterday, providers=PROVIDERS)
    snapshot, fallback_assets = make_snapshot(
        dataset,
        result=stored_result(research, args.run_id),
        promotion_event_id=promotion.key.removeprefix("promotion:forecast:"),
    )
    receipt = PortfolioResearchRepository(store, research).put_forecast_snapshot(snapshot)
    return _report(
        args.output,
        {
            "run_id": args.run_id,
            "promotion_event_key": promotion.key,
            "forecast_snapshot_id": snapshot.snapshot_id,
            "forecast_snapshot_record_id": receipt.record_id,
            "forecast_market_only_fallback_assets": list(fallback_assets),
        },
    )


def ingest_latest(
    repository: CryptoResearchRepository,
    *,
    end: date,
    adapters: Sequence[tuple[Callable[[], CryptoDataProvider], str, ObservationChannel]] = (
        INGESTION
    ),
) -> list[dict[str, object]]:
    """Ingest every v3 source from the day after its newest stored day through ``end``.

    A source with nothing new (a provider that has not published yet, or a GDELT outage) is
    reported as failed and the others continue; the feature builder then treats it as stale.
    """
    latest = _latest_days(repository.observations())
    service = CryptoIngestionService(repository)
    identifier = uuid.uuid4().hex
    receipts: list[dict[str, object]] = []
    for factory, provider, channel in adapters:
        adapter = factory()
        stored = latest.get((provider, channel))
        start = START if stored is None else stored + timedelta(days=1)
        if start > end:
            receipts.append({"adapter": adapter.adapter_id, "status": "up-to-date"})
            continue
        assets = tuple(asset for asset in CryptoAsset if asset in adapter.supported_assets)
        try:
            receipt = service.ingest_archived(
                adapter,
                assets=assets,
                start_utc=datetime.combine(start, time.min, tzinfo=UTC),
                end_utc=datetime.combine(end, time.max, tzinfo=UTC),
                attempt_id=f"prospective-ingest-{identifier}-{adapter.adapter_id}",
            )
        except Exception as exc:  # noqa: BLE001 - one source failing must not stop the rest
            receipts.append(
                {"adapter": adapter.adapter_id, "status": "failed", "error": str(exc)[:300]}
            )
            continue
        receipts.append({"adapter": adapter.adapter_id, "status": "ingested", **receipt.__dict__})
    return receipts


def freeze(
    crypto: CryptoResearchRepository,
    research: ResearchRunRepository,
    *,
    end: date,
    epochs: int,
    output: Path | None,
) -> int:
    if epochs < 1:
        raise ValueError("epochs must be positive")
    dataset = build_current_dataset(crypto, end=end, providers=PROVIDERS)
    crypto.put_feature_dataset_archive(
        dataset_hash=dataset.dataset_hash, rows=dataset.rows, manifest=dataset.manifest
    )
    result = run_forward_research(dataset, config=ProspectiveRunConfig(epochs=epochs))
    persisted = research.put_completed_run(result.manifest, result.artifacts)
    return _report(
        output,
        {
            "run_id": result.run_id,
            "manifest_key": persisted.manifest_key,
            "frozen_at_utc": result.manifest["completed_at_utc"],
            "dataset_hash": dataset.dataset_hash,
            "prospective": result.manifest["prospective"],
            "adaptive_calibration": result.manifest["adaptive_calibration"],
            "model_hashes": result.manifest["model_hashes"],
        },
    )


def issue(
    crypto: CryptoResearchRepository,
    research: ResearchRunRepository,
    ledger: ProspectiveLedgerRepository,
    *,
    run_id: str,
    output: Path | None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> int:
    """Record today's forecast for yesterday's decision date before any outcome exists."""
    decision_date = now().date() - timedelta(days=1)
    if ledger.has_entry(run_id, decision_date):
        return _report(
            output,
            {"run_id": run_id, "decision_date": str(decision_date), "status": "already-issued"},
        )
    receipts = ingest_latest(crypto, end=decision_date)
    dataset = build_current_dataset(crypto, end=decision_date, providers=PROVIDERS)
    entry = forecast_entry(dataset, stored_result(research, run_id), issued_at_utc=now())
    stored = ledger.put_entry(entry)
    return _report(
        output,
        {
            "run_id": run_id,
            "decision_date": entry["decision_date"],
            "status": "issued",
            "entry_key": stored.key,
            "entry_hash": entry["entry_hash"],
            "fallback_assets": [
                item["asset"]
                for item in cast(list[dict[str, object]], entry["forecasts"])
                if item["model"] == "deployable"
                and item["path"] == "fallback"
                and item["horizon_days"] == 15
            ],
            "ingestion": receipts,
        },
    )


def forecast_entry(
    dataset: FeatureDataset, result: ForwardResearchResult, *, issued_at_utc: datetime
) -> dict[str, object]:
    manifest, artifacts = result.manifest, result.artifacts
    horizons = cast(list[int], cast(dict[str, object], manifest["prospective"])["horizons"])
    hashes = cast(dict[str, str], manifest["artifact_hashes"])
    calibration = cast(dict[str, object], manifest["adaptive_calibration"])
    deployment = str(manifest["deployment_model_artifact"])
    fallback = str(manifest["fallback_model_artifact"])
    primary_models, _ = restore_models(
        lambda: ThreeAssetMSPCIFormer(fusion_mode=FusionMode.ADAPTIVE, horizon_count=len(horizons)),
        artifacts[deployment],
    )
    fallback_models, _ = restore_models(
        lambda: ThreeAssetMSPCIFormer(
            fusion_mode=FusionMode.MARKET_ONLY, horizon_count=len(horizons)
        ),
        artifacts[fallback],
    )
    current = infer_current_forecast(
        dataset,
        model=primary_models,
        standardizer=standardizer_from_artifact(artifacts[str(manifest["standardizer_artifact"])]),
        calibration=calibration,
        fallback_model=fallback_models,
    )
    return ledger_entry(
        run_id=result.run_id,
        protocol=str(manifest["evaluation_protocol"]),
        decision_time_utc=current.decision_time_utc,
        issued_at_utc=issued_at_utc,
        horizons=horizons,
        expected=current.expected,
        probability_up=current.probability_up,
        p10=current.p10,
        p50=current.p50,
        p90=current.p90,
        fallback_used=current.fallback_used,
        no_change_adjustment=cast(list[float], calibration["no_change_adjustment"]),
        model_hashes={"deployment": hashes[deployment], "fallback": hashes[fallback]},
        calibration_hash=hashes["adaptive-calibration.json"],
        dataset_hash=dataset.dataset_hash,
    )


def score(
    crypto: CryptoResearchRepository,
    ledger: ProspectiveLedgerRepository,
    *,
    run_id: str,
    output: Path | None,
) -> int:
    scorecard = score_ledger(ledger.entries(run_id), price_map(crypto.observations()))
    gate = cast(dict[str, object], scorecard["gate"])
    if gate["status"] in ("passed", "failed") and ledger.gate_decision(run_id) is None:
        ledger.put_gate_decision(gate_decision(run_id, scorecard))
    stored = ledger.gate_decision(run_id)
    return _report(
        output,
        {
            "run_id": run_id,
            "scorecard": scorecard,
            "stored_gate_decision": None if stored is None else stored["status"],
        },
    )


def stored_result(research: ResearchRunRepository, run_id: str) -> ForwardResearchResult:
    manifest = research.run_manifest(run_id)
    names = (
        str(manifest["deployment_model_artifact"]),
        str(manifest["fallback_model_artifact"]),
        str(manifest["standardizer_artifact"]),
        "adaptive-calibration.json",
    )
    return ForwardResearchResult(
        run_id=run_id,
        dataset_hash=str(manifest["dataset_hash"]),
        prediction_hash=str(manifest["prediction_hash"]),
        manifest=manifest,
        artifacts={name: research.restore_artifact(run_id, name) for name in names},
    )


def price_map(observations: Sequence[ProviderObservation]) -> dict[tuple[str, date], float]:
    """Coin Metrics daily closes keyed by asset and day, newest retrieval winning."""
    selected: dict[tuple[str, date], ProviderObservation] = {}
    for item in observations:
        if (
            item.provider != "coin-metrics"
            or item.channel is not ObservationChannel.MARKET
            or item.metric != "price_usd"
            or item.decimal_value is None
        ):
            continue
        key = (item.asset.value, item.observed_at_utc.date())
        current = selected.get(key)
        if current is None or item.retrieved_at_utc > current.retrieved_at_utc:
            selected[key] = item
    return {key: float(cast(str, item.decimal_value)) for key, item in selected.items()}


def _latest_days(
    observations: Sequence[ProviderObservation],
) -> dict[tuple[str, ObservationChannel], date]:
    latest: dict[tuple[str, ObservationChannel], date] = {}
    for item in observations:
        key = (item.provider, item.channel)
        day = item.observed_at_utc.date()
        if item.decimal_value is not None and (key not in latest or day > latest[key]):
            latest[key] = day
    return latest


def _research_repository(
    store: DockerResilientDBEventStore, args: argparse.Namespace
) -> ResearchRunRepository:
    environment_key = os.environ.get(args.encryption_key_env)
    key = load_research_key(
        variable=args.encryption_key_env,
        docker=args.docker,
        docker_host=args.docker_host,
        container=args.encryption_key_container,
        path=args.encryption_key_path,
    )
    key_id = (
        "local-research-blob-key-v1"
        if environment_key is None
        else "local-research-override-" + hashlib.sha256(key).hexdigest()[:16]
    )
    return ResearchRunRepository(
        store, EncryptedBlobRepository(store, AesGcmCipher(key, key_id=key_id))
    )


def _report(path: Path | None, document: dict[str, object]) -> int:
    rendered = json.dumps(document, indent=2, sort_keys=True, default=str) + "\n"
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
