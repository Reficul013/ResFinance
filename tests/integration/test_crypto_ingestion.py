from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import UTC, date, datetime

import pytest

from ml.features.point_in_time import PointInTimeFeatureBuilder
from server.app.application.crypto_ingestion import CryptoIngestionService
from server.app.domain.crypto import (
    CryptoAsset,
    ObservationChannel,
    ProviderObservation,
)
from server.app.infrastructure.crypto_repository import (
    CryptoResearchRepository,
    ImmutableResearchRecordConflict,
)
from server.app.workers.crypto_ingestion import IngestionJob, run_ingestion_job


class MemoryKeyValueStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def put(self, key: str, value: str) -> None:
        self.values[key] = value

    def range_values(self, prefix: str) -> Sequence[str]:
        return [self.values[key] for key in sorted(self.values) if key.startswith(prefix)]


class SyntheticProvider:
    provider = "synthetic-provider"
    adapter_id = "synthetic-provider"
    supported_assets = frozenset(CryptoAsset)

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


class ScopedSyntheticProvider(SyntheticProvider):
    def __init__(
        self,
        *,
        adapter_id: str,
        supported_assets: frozenset[CryptoAsset],
        observations: Sequence[ProviderObservation],
    ) -> None:
        super().__init__(observations)
        self.adapter_id = adapter_id
        self.supported_assets = supported_assets


def item(
    *,
    asset: CryptoAsset = CryptoAsset.BTC,
    channel: ObservationChannel = ObservationChannel.MARKET,
    metric: str = "price_usd",
    day: int = 1,
    available_day: int | None = None,
    value: str | None = "100",
    revision: str = "synthetic-v1",
    provider: str = "synthetic-provider",
) -> ProviderObservation:
    observed = datetime(2025, 1, day, tzinfo=UTC)
    available = datetime(2025, 1, available_day or day + 1, tzinfo=UTC)
    return ProviderObservation(
        asset=asset,
        channel=channel,
        metric=metric,
        interval="1d",
        observed_at_utc=observed,
        available_at_utc=available,
        retrieved_at_utc=datetime(2026, 10, 14, tzinfo=UTC),
        decimal_value=value,
        missing=value is None,
        provider=provider,
        source_reference="https://example.test/synthetic",
        provider_revision=revision,
        response_sha256=hashlib.sha256(revision.encode()).hexdigest(),
        terms_reference="https://example.test/terms",
        license_status="synthetic-test-data",
    )


def test_repeat_ingestion_is_idempotent_and_failed_provider_preserves_data() -> None:
    store = MemoryKeyValueStore()
    repository = CryptoResearchRepository(store)
    service = CryptoIngestionService(repository)
    provider = SyntheticProvider((item(), item(day=2, value="105")))
    start = datetime(2025, 1, 1, tzinfo=UTC)
    end = datetime(2025, 1, 2, tzinfo=UTC)

    first = service.ingest(
        provider,
        assets=(CryptoAsset.BTC,),
        start_utc=start,
        end_utc=end,
        attempt_id="success-1",
    )
    repeated = service.ingest(
        provider,
        assets=(CryptoAsset.BTC,),
        start_utc=start,
        end_utc=end,
        attempt_id="success-2",
    )
    before_failure = tuple(repository.observations())

    with pytest.raises(RuntimeError, match="provider unavailable"):
        service.ingest(
            SyntheticProvider(error=RuntimeError("provider unavailable")),
            assets=(CryptoAsset.BTC,),
            start_utc=start,
            end_utc=end,
            attempt_id="failure-1",
        )

    assert first.inserted_count == 2
    assert repeated.inserted_count == 0
    assert repeated.deduplicated_count == 2
    assert tuple(repository.observations()) == before_failure
    assert [attempt["status"] for attempt in repository.ingestion_attempts()] == [
        "failed",
        "succeeded",
        "succeeded",
    ]


def test_repeat_retrieval_time_does_not_duplicate_an_unchanged_observation() -> None:
    repository = CryptoResearchRepository(MemoryKeyValueStore())
    original = item()
    later_retrieval = ProviderObservation.from_dict(
        {
            **original.to_dict(),
            "retrieved_at_utc": "2026-10-15T00:00:00Z",
        }
    )

    first = repository.put_observation(original)
    repeated = repository.put_observation(later_retrieval)

    assert not first.deduplicated
    assert repeated.deduplicated
    assert repeated.record_id == first.record_id


def test_archived_ingestion_is_checksum_verified_idempotent_and_restorable() -> None:
    store = MemoryKeyValueStore()
    repository = CryptoResearchRepository(store)
    service = CryptoIngestionService(repository)
    observations = (item(), item(day=2, value="105"))
    provider = SyntheticProvider(observations)
    start = datetime(2025, 1, 1, tzinfo=UTC)
    end = datetime(2025, 1, 2, tzinfo=UTC)

    first = service.ingest_archived(
        provider,
        assets=(CryptoAsset.BTC,),
        start_utc=start,
        end_utc=end,
        attempt_id="archive-1",
    )
    repeated = service.ingest_archived(
        provider,
        assets=(CryptoAsset.BTC,),
        start_utc=start,
        end_utc=end,
        attempt_id="archive-2",
    )
    later = tuple(
        ProviderObservation.from_dict(
            {**observation.to_dict(), "retrieved_at_utc": "2026-10-15T00:00:00Z"}
        )
        for observation in observations
    )
    later_retrieval = service.ingest_archived(
        SyntheticProvider(later),
        assets=(CryptoAsset.BTC,),
        start_utc=start,
        end_utc=end,
        attempt_id="archive-3",
    )

    assert first.inserted_count == 2
    assert repeated.inserted_count == 0
    assert repeated.deduplicated_count == 2
    assert later_retrieval.inserted_count == 0
    assert repository.observations() == list(observations)
    assert len([key for key in store.values if key.startswith("license:")]) == 1


def test_immutable_observation_rejects_same_identity_with_changed_value() -> None:
    repository = CryptoResearchRepository(MemoryKeyValueStore())
    repository.put_observation(item())

    with pytest.raises(ImmutableResearchRecordConflict):
        repository.put_observation(item(value="999"))


def test_empty_provider_batch_is_recorded_as_failure() -> None:
    repository = CryptoResearchRepository(MemoryKeyValueStore())
    service = CryptoIngestionService(repository)

    with pytest.raises(ValueError, match="no observations"):
        service.ingest(
            SyntheticProvider(),
            assets=(CryptoAsset.BTC,),
            start_utc=datetime(2025, 1, 1, tzinfo=UTC),
            end_utc=datetime(2025, 1, 1, tzinfo=UTC),
            attempt_id="empty-provider",
        )

    assert repository.ingestion_attempts()[0]["status"] == "failed"


def test_point_in_time_join_excludes_future_revision_and_persists_masks() -> None:
    observations = [
        item(value="100", revision="revision-1"),
        item(value="999", available_day=4, revision="revision-2"),
        item(value="777", provider="unapproved-provider"),
        item(day=2, value="110"),
        item(
            asset=CryptoAsset.SOL,
            channel=ObservationChannel.ON_CHAIN,
            metric="solana_tvl_usd",
            value=None,
        ),
    ]
    builder = PointInTimeFeatureBuilder()
    dataset = builder.build(
        observations,
        assets=(CryptoAsset.BTC, CryptoAsset.SOL),
        providers=("synthetic-provider",),
        start=date(2025, 1, 1),
        end=date(2025, 1, 2),
        as_of_utc=datetime(2025, 1, 3, tzinfo=UTC),
    )
    btc_day_one = next(
        row
        for row in dataset.rows
        if row["asset"] == "BTC" and row["timestamp_utc"].startswith("2025-01-01")
    )
    btc_day_two = next(
        row
        for row in dataset.rows
        if row["asset"] == "BTC" and row["timestamp_utc"].startswith("2025-01-02")
    )
    sol_day_one = next(row for row in dataset.rows if row["asset"] == "SOL")

    assert btc_day_one["values"]["market_price_usd"] == "100"  # type: ignore[index]
    assert btc_day_two["values"]["market_return_1d"] == "0.1"  # type: ignore[index]
    assert sol_day_one["values"]["on_chain_solana_tvl_usd"] is None  # type: ignore[index]
    assert not sol_day_one["availability_masks"]["on_chain_solana_tvl_usd"]  # type: ignore[index]

    repository = CryptoResearchRepository(MemoryKeyValueStore())
    repository.put_feature_dataset(
        dataset_hash=dataset.dataset_hash,
        rows=dataset.rows,
        manifest=dataset.manifest,
    )
    repeated = repository.put_feature_dataset(
        dataset_hash=dataset.dataset_hash,
        rows=dataset.rows,
        manifest=dataset.manifest,
    )
    assert all(result.deduplicated for result in repeated)
    assert repository.dataset_manifest(dataset.dataset_hash)["rows_sha256"]

    tampered_rows = list(dataset.rows)
    tampered_rows[0] = {**tampered_rows[0], "asset": "DOGE"}
    with pytest.raises(ValueError, match="rows checksum"):
        repository.put_feature_dataset(
            dataset_hash=dataset.dataset_hash,
            rows=tampered_rows,
            manifest=dataset.manifest,
        )

    with pytest.raises(ValueError, match="dataset hash"):
        repository.put_feature_dataset(
            dataset_hash="0" * 64,
            rows=dataset.rows,
            manifest=dataset.manifest,
        )


def test_delayed_news_uses_the_latest_available_day_and_reports_its_age() -> None:
    observations = [item(day=day, value=str(100 + day)) for day in range(1, 5)] + [
        item(
            channel=ObservationChannel.SENTIMENT,
            metric="average_tone",
            day=day,
            available_day=day + 2,
            value=str(-day),
        )
        for day in range(1, 4)
    ]
    dataset = PointInTimeFeatureBuilder().build(
        observations,
        assets=(CryptoAsset.BTC,),
        providers=("synthetic-provider",),
        start=date(2025, 1, 1),
        end=date(2025, 1, 4),
        as_of_utc=datetime(2025, 1, 5, tzinfo=UTC),
    )
    rows = {str(row["timestamp_utc"])[:10]: row for row in dataset.rows}

    # Day D's decision (D+1 00:00) can use news about D-1, which is published at D+1.
    assert rows["2025-01-01"]["values"]["sentiment_average_tone"] is None  # type: ignore[index]
    assert rows["2025-01-03"]["values"]["sentiment_average_tone"] == "-2"  # type: ignore[index]
    assert rows["2025-01-03"]["availability_masks"]["sentiment_average_tone"]  # type: ignore[index]
    assert rows["2025-01-03"]["feature_age_days"]["sentiment_average_tone"] == 0  # type: ignore[index]
    assert rows["2025-01-03"]["values"]["market_price_usd"] == "103"  # type: ignore[index]
    assert dataset.manifest["source_alignment"] == "latest-available-observation"


def test_stale_non_market_source_is_masked_after_the_maximum_age() -> None:
    observations = [item(day=day, value="100") for day in range(1, 9)] + [
        item(
            channel=ObservationChannel.SENTIMENT,
            metric="average_tone",
            day=1,
            available_day=3,
            value="-1.5",
        )
    ]
    dataset = PointInTimeFeatureBuilder().build(
        observations,
        assets=(CryptoAsset.BTC,),
        providers=("synthetic-provider",),
        start=date(2025, 1, 1),
        end=date(2025, 1, 8),
        as_of_utc=datetime(2025, 1, 9, tzinfo=UTC),
    )
    rows = {str(row["timestamp_utc"])[:10]: row for row in dataset.rows}
    fresh, stale = rows["2025-01-05"], rows["2025-01-06"]

    assert fresh["values"]["sentiment_average_tone"] == "-1.5"  # type: ignore[index]
    assert fresh["feature_age_days"]["sentiment_average_tone"] == 3  # type: ignore[index]
    assert stale["values"]["sentiment_average_tone"] is None  # type: ignore[index]
    assert not stale["availability_masks"]["sentiment_average_tone"]  # type: ignore[index]
    assert stale["feature_age_days"]["sentiment_average_tone"] == 4  # type: ignore[index]
    assert not stale["source_masks"]["sentiment"]  # type: ignore[index]


def test_feature_dataset_archive_round_trips_without_per_row_records() -> None:
    dataset = PointInTimeFeatureBuilder().build(
        (item(), item(day=2, value="105")),
        assets=(CryptoAsset.BTC,),
        providers=("synthetic-provider",),
        start=date(2025, 1, 1),
        end=date(2025, 1, 2),
        as_of_utc=datetime(2025, 1, 3, tzinfo=UTC),
    )
    store = MemoryKeyValueStore()
    repository = CryptoResearchRepository(store)

    first = repository.put_feature_dataset_archive(
        dataset_hash=dataset.dataset_hash,
        rows=dataset.rows,
        manifest=dataset.manifest,
    )
    repeated = repository.put_feature_dataset_archive(
        dataset_hash=dataset.dataset_hash,
        rows=dataset.rows,
        manifest=dataset.manifest,
    )

    assert not any(key.startswith("feat:") for key in store.values)
    assert repository.feature_rows(dataset.dataset_hash) == list(dataset.rows)
    assert any(not item.deduplicated for item in first)
    assert all(item.deduplicated for item in repeated)


def test_fourth_asset_is_rejected_at_ingestion_and_feature_boundaries() -> None:
    service = CryptoIngestionService(CryptoResearchRepository(MemoryKeyValueStore()))
    with pytest.raises(ValueError, match="BTC, ETH, or SOL"):
        service.ingest(
            SyntheticProvider(),
            assets=("DOGE",),
            start_utc=datetime(2025, 1, 1, tzinfo=UTC),
            end_utc=datetime(2025, 1, 1, tzinfo=UTC),
            attempt_id="doge-ingestion",
        )

    with pytest.raises(ValueError, match="BTC, ETH, or SOL"):
        PointInTimeFeatureBuilder().build(
            (),
            assets=("DOGE",),
            providers=("synthetic-provider",),
            start=date(2025, 1, 1),
            end=date(2025, 1, 1),
            as_of_utc=datetime(2025, 1, 2, tzinfo=UTC),
        )


def test_one_day_return_does_not_bridge_a_missing_calendar_day() -> None:
    dataset = PointInTimeFeatureBuilder().build(
        (item(day=1, value="100"), item(day=3, value="120")),
        assets=(CryptoAsset.BTC,),
        providers=("synthetic-provider",),
        start=date(2025, 1, 1),
        end=date(2025, 1, 3),
        as_of_utc=datetime(2025, 1, 4, tzinfo=UTC),
    )
    day_three = dataset.rows[2]

    assert day_three["values"]["market_return_1d"] is None  # type: ignore[index]
    assert not day_three["availability_masks"]["market_return_1d"]  # type: ignore[index]


def test_worker_scopes_assets_and_attempt_ids_per_adapter() -> None:
    repository = CryptoResearchRepository(MemoryKeyValueStore())
    service = CryptoIngestionService(repository)
    market = ScopedSyntheticProvider(
        adapter_id="market",
        supported_assets=frozenset(CryptoAsset),
        observations=tuple(item(asset=asset) for asset in CryptoAsset),
    )
    on_chain = ScopedSyntheticProvider(
        adapter_id="on-chain",
        supported_assets=frozenset((CryptoAsset.BTC, CryptoAsset.ETH)),
        observations=(
            item(
                asset=CryptoAsset.BTC,
                channel=ObservationChannel.ON_CHAIN,
                metric="active_addresses",
                value="10",
            ),
            item(
                asset=CryptoAsset.ETH,
                channel=ObservationChannel.ON_CHAIN,
                metric="active_addresses",
                value="20",
            ),
        ),
    )

    receipts = run_ingestion_job(
        service,
        IngestionJob(
            job_id="daily-2025-01-01",
            assets=tuple(CryptoAsset),
            start_utc=datetime(2025, 1, 1, tzinfo=UTC),
            end_utc=datetime(2025, 1, 1, tzinfo=UTC),
        ),
        (market, on_chain),
    )

    assert [receipt.observation_count for receipt in receipts] == [3, 2]
    assert {attempt["attempt_id"] for attempt in repository.ingestion_attempts()} == {
        "daily-2025-01-01-market",
        "daily-2025-01-01-on-chain",
    }
