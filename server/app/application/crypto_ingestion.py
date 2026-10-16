from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from server.app.application.ports import ImmutableStoreResult
from server.app.application.providers import CryptoDataProvider
from server.app.domain.crypto import CryptoAsset, ProviderObservation, utc_datetime


class CryptoObservationRepository(Protocol):
    def put_observation(self, observation: ProviderObservation) -> ImmutableStoreResult: ...

    def put_observation_archive(
        self, observations: Sequence[ProviderObservation]
    ) -> ImmutableStoreResult: ...

    def record_ingestion_attempt(self, record: dict[str, object]) -> object: ...


@dataclass(frozen=True)
class IngestionReceipt:
    attempt_id: str
    provider: str
    observation_count: int
    inserted_count: int
    deduplicated_count: int
    observation_set_sha256: str


class CryptoIngestionService:
    def __init__(self, repository: CryptoObservationRepository) -> None:
        self._repository = repository

    def ingest(
        self,
        provider: CryptoDataProvider,
        *,
        assets: Sequence[CryptoAsset | str],
        start_utc: datetime,
        end_utc: datetime,
        attempt_id: str,
    ) -> IngestionReceipt:
        return self._ingest(
            provider,
            assets=assets,
            start_utc=start_utc,
            end_utc=end_utc,
            attempt_id=attempt_id,
            archive=False,
        )

    def ingest_archived(
        self,
        provider: CryptoDataProvider,
        *,
        assets: Sequence[CryptoAsset | str],
        start_utc: datetime,
        end_utc: datetime,
        attempt_id: str,
    ) -> IngestionReceipt:
        """Persist a validated provider response as a checksum-addressed archive."""
        return self._ingest(
            provider,
            assets=assets,
            start_utc=start_utc,
            end_utc=end_utc,
            attempt_id=attempt_id,
            archive=True,
        )

    def _ingest(
        self,
        provider: CryptoDataProvider,
        *,
        assets: Sequence[CryptoAsset | str],
        start_utc: datetime,
        end_utc: datetime,
        attempt_id: str,
        archive: bool,
    ) -> IngestionReceipt:
        start = utc_datetime(start_utc, field="start_utc")
        end = utc_datetime(end_utc, field="end_utc")
        if end < start:
            raise ValueError("ingestion end cannot precede start")
        parsed_assets = tuple(
            item if isinstance(item, CryptoAsset) else CryptoAsset.parse(item) for item in assets
        )
        if not parsed_assets or len(set(parsed_assets)) != len(parsed_assets):
            raise ValueError("ingestion assets must be a non-empty unique sequence")
        requested_assets = set(parsed_assets)
        started_at = datetime.now(UTC)
        try:
            observations = tuple(
                provider.observations(assets=parsed_assets, start_utc=start, end_utc=end)
            )
            self._validate_batch(
                observations,
                provider=provider.provider,
                requested_assets=requested_assets,
                start=start,
                end=end,
            )
            observation_set_sha256 = hashlib.sha256(
                _canonical_json([item.record_id for item in observations])
            ).hexdigest()
            if archive:
                archive_result = self._repository.put_observation_archive(observations)
                inserted = 0 if archive_result.deduplicated else len(observations)
                deduplicated = len(observations) - inserted
            else:
                results = tuple(self._repository.put_observation(item) for item in observations)
                inserted = sum(not item.deduplicated for item in results)
                deduplicated = len(results) - inserted
            completed_at = datetime.now(UTC)
            self._repository.record_ingestion_attempt(
                {
                    "attempt_id": attempt_id,
                    "provider": provider.provider,
                    "status": "succeeded",
                    "assets": [asset.value for asset in parsed_assets],
                    "start_utc": _iso(start),
                    "end_utc": _iso(end),
                    "started_at_utc": _iso(started_at),
                    "completed_at_utc": _iso(completed_at),
                    "observation_count": len(observations),
                    "inserted_count": inserted,
                    "deduplicated_count": deduplicated,
                    "observation_set_sha256": observation_set_sha256,
                }
            )
            return IngestionReceipt(
                attempt_id=attempt_id,
                provider=provider.provider,
                observation_count=len(observations),
                inserted_count=inserted,
                deduplicated_count=deduplicated,
                observation_set_sha256=observation_set_sha256,
            )
        except Exception as exc:
            self._repository.record_ingestion_attempt(
                {
                    "attempt_id": attempt_id,
                    "provider": provider.provider,
                    "status": "failed",
                    "assets": [asset.value for asset in parsed_assets],
                    "start_utc": _iso(start),
                    "end_utc": _iso(end),
                    "started_at_utc": _iso(started_at),
                    "completed_at_utc": _iso(datetime.now(UTC)),
                    "error_type": type(exc).__name__,
                    "error_sha256": hashlib.sha256(str(exc).encode()).hexdigest(),
                }
            )
            raise

    @staticmethod
    def _validate_batch(
        observations: Sequence[ProviderObservation],
        *,
        provider: str,
        requested_assets: set[CryptoAsset],
        start: datetime,
        end: datetime,
    ) -> None:
        if not observations:
            raise ValueError("provider returned no observations")
        identities: dict[tuple[object, ...], str] = {}
        for item in observations:
            if item.provider != provider:
                raise ValueError("provider batch contains a mismatched provider name")
            if item.asset not in requested_assets:
                raise ValueError("provider returned an unrequested crypto asset")
            if not start.date() <= item.observed_at_utc.date() <= end.date():
                raise ValueError("provider returned an observation outside the requested range")
            identity = (
                item.asset,
                item.channel,
                item.metric,
                item.interval,
                item.observed_at_utc,
                item.provider_revision,
            )
            previous = identities.get(identity)
            if previous is not None:
                raise ValueError("provider batch contains duplicate observations")
            identities[identity] = item.record_id


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )
