from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from ml.features.point_in_time import PointInTimeFeatureBuilder
from server.app.application.crypto_ingestion import CryptoIngestionService
from server.app.domain.crypto import (
    CryptoAsset,
    ObservationChannel,
    ProviderObservation,
)
from server.app.infrastructure.crypto_repository import CryptoResearchRepository
from server.app.infrastructure.resilientdb_cli import DockerResilientDBEventStore


class SyntheticAcceptanceProvider:
    provider = "milestone5-acceptance"
    adapter_id = "milestone5-acceptance"
    supported_assets: frozenset[CryptoAsset] = frozenset(
        (CryptoAsset.BTC, CryptoAsset.ETH, CryptoAsset.SOL)
    )

    def __init__(
        self,
        observations: Sequence[ProviderObservation] = (),
        *,
        error: Exception | None = None,
    ) -> None:
        self._observations = observations
        self._error = error

    def observations(
        self,
        *,
        assets: Sequence[CryptoAsset],
        start_utc: datetime,
        end_utc: datetime,
    ) -> Sequence[ProviderObservation]:
        del assets, start_utc, end_utc
        if self._error is not None:
            raise self._error
        return self._observations


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Prove Milestone 5 idempotency, failure isolation, point-in-time joins, "
            "availability masks, and the three-asset boundary against ResilientDB."
        )
    )
    parser.add_argument("--docker", type=Path, default=Path("docker"))
    parser.add_argument("--docker-host")
    parser.add_argument("--container", default="resfinance-resdb-tools")
    parser.add_argument("--config", default="/config/client.config")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_id = uuid.uuid4().hex
    revision = f"synthetic-{run_id}"
    store = DockerResilientDBEventStore(
        docker=args.docker,
        docker_host=args.docker_host,
        container=args.container,
        config_path=args.config,
        timeout_seconds=30,
    )
    repository = CryptoResearchRepository(store)
    service = CryptoIngestionService(repository)
    start = datetime(2025, 1, 1, tzinfo=UTC)
    end = datetime(2025, 1, 3, tzinfo=UTC)
    observations = _synthetic_observations(revision)
    provider = SyntheticAcceptanceProvider(observations)

    first = service.ingest(
        provider,
        assets=tuple(CryptoAsset),
        start_utc=start,
        end_utc=end,
        attempt_id=f"{run_id}-initial",
    )
    repeated = service.ingest(
        provider,
        assets=tuple(CryptoAsset),
        start_utc=start,
        end_utc=end,
        attempt_id=f"{run_id}-repeat",
    )
    if first.inserted_count != len(observations):
        raise RuntimeError("initial ingestion did not insert every observation")
    if repeated.inserted_count != 0 or repeated.deduplicated_count != len(observations):
        raise RuntimeError("repeat ingestion was not idempotent")

    before_failure = len(repository.observations())
    try:
        service.ingest(
            SyntheticAcceptanceProvider(error=RuntimeError("injected-provider-failure")),
            assets=tuple(CryptoAsset),
            start_utc=start,
            end_utc=end,
            attempt_id=f"{run_id}-failure",
        )
    except RuntimeError as exc:
        if str(exc) != "injected-provider-failure":
            raise
    else:
        raise RuntimeError("injected provider failure was not raised")
    after_failure = len(repository.observations())
    if after_failure != before_failure:
        raise RuntimeError("provider failure changed persisted observations")

    dataset = PointInTimeFeatureBuilder().build(
        repository.observations(),
        assets=tuple(CryptoAsset),
        providers=(provider.provider,),
        start=date(2025, 1, 1),
        end=date(2025, 1, 3),
        as_of_utc=datetime(2025, 1, 4, tzinfo=UTC),
    )
    feature_first = repository.put_feature_dataset(
        dataset_hash=dataset.dataset_hash,
        rows=dataset.rows,
        manifest=dataset.manifest,
    )
    feature_repeated = repository.put_feature_dataset(
        dataset_hash=dataset.dataset_hash,
        rows=dataset.rows,
        manifest=dataset.manifest,
    )
    if not all(result.deduplicated for result in feature_repeated):
        raise RuntimeError("repeat feature persistence was not idempotent")

    btc_day_one = next(
        row
        for row in dataset.rows
        if row["asset"] == "BTC" and str(row["timestamp_utc"]).startswith("2025-01-01")
    )
    values = btc_day_one["values"]
    if not isinstance(values, dict) or values["market_price_usd"] != "100":
        raise RuntimeError("point-in-time join leaked a future revision")
    sol_rows = [row for row in dataset.rows if row["asset"] == "SOL"]
    for row in sol_rows:
        masks = row["availability_masks"]
        values = row["values"]
        if (
            not isinstance(masks, dict)
            or not isinstance(values, dict)
            or masks["on_chain_solana_tvl_usd"]
            or values["on_chain_solana_tvl_usd"] is not None
        ):
            raise RuntimeError("SOL missingness was not retained as an explicit mask")

    fourth_asset_rejected = False
    try:
        service.ingest(
            provider,
            assets=("DOGE",),
            start_utc=start,
            end_utc=end,
            attempt_id=f"{run_id}-fourth-asset",
        )
    except ValueError:
        fourth_asset_rejected = True
    if not fourth_asset_rejected:
        raise RuntimeError("fourth asset was accepted")

    evidence = {
        "schema_version": 1,
        "completed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "scope": "local-synthetic-acceptance-on-real-resilientdb",
        "persistent_database": "Apache ResilientDB LevelDB backend",
        "assets": [asset.value for asset in CryptoAsset],
        "raw_observation_count": len(observations),
        "initial_inserted_count": first.inserted_count,
        "repeat_deduplicated_count": repeated.deduplicated_count,
        "provider_failure_preserved_observation_count": before_failure == after_failure,
        "failed_attempt_recorded": any(
            attempt.get("attempt_id") == f"{run_id}-failure" and attempt.get("status") == "failed"
            for attempt in repository.ingestion_attempts()
        ),
        "dataset_hash": dataset.dataset_hash,
        "feature_row_count": len(dataset.rows),
        "feature_inserted_count": sum(not result.deduplicated for result in feature_first),
        "feature_repeat_idempotent": all(result.deduplicated for result in feature_repeated),
        "point_in_time_leakage_rejected": True,
        "sol_missingness_is_mask_not_zero": True,
        "fourth_asset_rejected": fourth_asset_rejected,
    }
    rendered = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    print(rendered, end="")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    return 0


def _synthetic_observations(revision: str) -> tuple[ProviderObservation, ...]:
    retrieved = datetime(2026, 10, 14, tzinfo=UTC)
    checksum = hashlib.sha256(revision.encode()).hexdigest()
    observations: list[ProviderObservation] = []
    prices = {
        CryptoAsset.BTC: ("100", "105", "110"),
        CryptoAsset.ETH: ("20", "21", "22"),
        CryptoAsset.SOL: ("5", "5.5", "6"),
    }
    for asset, daily_prices in prices.items():
        for offset, price in enumerate(daily_prices):
            observed = datetime(2025, 1, 1 + offset, tzinfo=UTC)
            observations.append(
                _observation(
                    asset=asset,
                    channel=ObservationChannel.MARKET,
                    metric="price_usd",
                    observed=observed,
                    available=observed + timedelta(days=1),
                    value=price,
                    revision=revision,
                    retrieved=retrieved,
                    checksum=checksum,
                )
            )
            observations.append(
                _observation(
                    asset=asset,
                    channel=ObservationChannel.SENTIMENT,
                    metric="average_tone",
                    observed=observed,
                    available=observed + timedelta(days=1),
                    value=str(offset - 1),
                    revision=revision,
                    retrieved=retrieved,
                    checksum=checksum,
                )
            )
            if asset in (CryptoAsset.BTC, CryptoAsset.ETH):
                observations.append(
                    _observation(
                        asset=asset,
                        channel=ObservationChannel.ON_CHAIN,
                        metric="active_addresses",
                        observed=observed,
                        available=observed + timedelta(days=1),
                        value=str(1000 + offset),
                        revision=revision,
                        retrieved=retrieved,
                        checksum=checksum,
                    )
                )
            else:
                observations.append(
                    _observation(
                        asset=asset,
                        channel=ObservationChannel.ON_CHAIN,
                        metric="solana_tvl_usd",
                        observed=observed,
                        available=observed + timedelta(days=1),
                        value=None,
                        revision=revision,
                        retrieved=retrieved,
                        checksum=checksum,
                    )
                )
    observations.append(
        _observation(
            asset=CryptoAsset.BTC,
            channel=ObservationChannel.MARKET,
            metric="price_usd",
            observed=datetime(2025, 1, 1, tzinfo=UTC),
            available=datetime(2025, 1, 5, tzinfo=UTC),
            value="999",
            revision=f"{revision}-future",
            retrieved=retrieved,
            checksum=hashlib.sha256(f"{revision}-future".encode()).hexdigest(),
        )
    )
    return tuple(observations)


def _observation(
    *,
    asset: CryptoAsset,
    channel: ObservationChannel,
    metric: str,
    observed: datetime,
    available: datetime,
    value: str | None,
    revision: str,
    retrieved: datetime,
    checksum: str,
) -> ProviderObservation:
    return ProviderObservation(
        asset=asset,
        channel=channel,
        metric=metric,
        interval="1d",
        observed_at_utc=observed,
        available_at_utc=available,
        retrieved_at_utc=retrieved,
        decimal_value=value,
        missing=value is None,
        provider="milestone5-acceptance",
        source_reference="synthetic://milestone5-acceptance",
        provider_revision=revision,
        response_sha256=checksum,
        terms_reference="synthetic://license",
        license_status="deterministic-synthetic-test-data",
    )


if __name__ == "__main__":
    raise SystemExit(main())
