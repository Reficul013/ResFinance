from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, cast

from server.app.application.ports import ImmutableStoreResult, KeyValueStore
from server.app.domain.crypto import CryptoAsset, ObservationChannel, ProviderObservation
from server.app.infrastructure.encryption import canonical_json_bytes


class ImmutableResearchRecordConflict(ValueError):
    pass


class CorruptResearchRecord(ValueError):
    pass


def _timestamp_key(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%S.%fZ")


def _safe_key_part(value: str) -> str:
    return value.replace(":", "-").replace("/", "-")


class CryptoResearchRepository:
    def __init__(self, store: KeyValueStore) -> None:
        self._store = store

    def put_observation(self, observation: ProviderObservation) -> ImmutableStoreResult:
        key = self.observation_key(observation)
        document = {**observation.to_dict(), "record_id": observation.record_id}
        existing = self._store.get(key)
        if existing is not None:
            stored = ProviderObservation.from_dict(self._load(existing))
            if stored.record_id != observation.record_id:
                raise ImmutableResearchRecordConflict(
                    f"immutable research observation already exists with different content: {key}"
                )
            result = ImmutableStoreResult(
                key=key, record_id=observation.record_id, deduplicated=True
            )
        else:
            self._put_immutable(key, document)
            result = ImmutableStoreResult(
                key=key, record_id=observation.record_id, deduplicated=False
            )
        self._put_license(observation)
        return result

    def put_observations(
        self, observations: Sequence[ProviderObservation]
    ) -> tuple[ImmutableStoreResult, ...]:
        return tuple(self.put_observation(item) for item in observations)

    def observations(self) -> list[ProviderObservation]:
        values: list[str] = []
        for prefix in ("mkt:", "chain:", "sent:"):
            values.extend(self._store.range_values(prefix))
        records = [ProviderObservation.from_dict(self._load(value)) for value in values]
        records.sort(
            key=lambda item: (
                item.observed_at_utc,
                item.asset.value,
                item.channel.value,
                item.metric,
                item.available_at_utc,
                item.provider_revision,
            )
        )
        return records

    def record_ingestion_attempt(self, record: dict[str, object]) -> ImmutableStoreResult:
        attempt_id = record.get("attempt_id")
        if not isinstance(attempt_id, str) or not attempt_id:
            raise ValueError("ingestion attempt requires an attempt_id")
        key = f"ingest:{_safe_key_part(attempt_id)}"
        return self._put_immutable(key, {"schema_version": 1, **record})

    def ingestion_attempts(self) -> list[dict[str, Any]]:
        return [self._load(value) for value in self._store.range_values("ingest:")]

    def put_feature_dataset(
        self,
        *,
        dataset_hash: str,
        rows: Sequence[dict[str, object]],
        manifest: dict[str, object],
    ) -> tuple[ImmutableStoreResult, ...]:
        if not rows:
            raise ValueError("feature dataset cannot be empty")
        manifest_core = {key: value for key, value in manifest.items() if key != "dataset_hash"}
        expected_dataset_hash = hashlib.sha256(canonical_json_bytes(manifest_core)).hexdigest()
        if manifest.get("dataset_hash") != dataset_hash or dataset_hash != expected_dataset_hash:
            raise ValueError("feature dataset hash does not match its manifest")
        if manifest.get("row_count") != len(rows):
            raise ValueError("feature manifest row count does not match")
        rows_sha256 = hashlib.sha256(canonical_json_bytes(rows)).hexdigest()
        if manifest.get("rows_sha256") != rows_sha256:
            raise ValueError("feature rows checksum does not match its manifest")
        results: list[ImmutableStoreResult] = []
        row_keys: set[str] = set()
        for row in rows:
            asset = CryptoAsset.parse(str(row["asset"])).value
            timestamp = str(row["timestamp_utc"])
            key = f"feat:{dataset_hash}:{asset}:{_safe_key_part(timestamp)}"
            if key in row_keys:
                raise ValueError("feature dataset contains a duplicate asset/timestamp row")
            row_keys.add(key)
            row_core = {key: value for key, value in row.items() if key != "row_sha256"}
            expected_row_hash = hashlib.sha256(canonical_json_bytes(row_core)).hexdigest()
            if row.get("row_sha256") != expected_row_hash:
                raise ValueError("feature row checksum does not match")
            results.append(self._put_immutable(key, row))
        results.append(self._put_immutable(f"dataset:{dataset_hash}:manifest", manifest))
        return tuple(results)

    def feature_rows(self, dataset_hash: str) -> list[dict[str, Any]]:
        values = self._store.range_values(f"feat:{dataset_hash}:")
        rows = [self._load(value) for value in values]
        rows.sort(key=lambda row: (str(row["timestamp_utc"]), str(row["asset"])))
        return rows

    def dataset_manifest(self, dataset_hash: str) -> dict[str, Any]:
        encoded = self._store.get(f"dataset:{dataset_hash}:manifest")
        if encoded is None:
            raise KeyError(dataset_hash)
        return self._load(encoded)

    @staticmethod
    def observation_key(observation: ProviderObservation) -> str:
        timestamp = _timestamp_key(observation.observed_at_utc)
        provider = _safe_key_part(observation.provider)
        revision = _safe_key_part(observation.provider_revision)
        metric = _safe_key_part(observation.metric)
        if observation.channel is ObservationChannel.MARKET:
            return (
                f"mkt:{observation.asset.value}:{observation.interval}:{timestamp}:"
                f"{provider}:{revision}:{metric}"
            )
        if observation.channel is ObservationChannel.ON_CHAIN:
            return f"chain:{observation.asset.value}:{metric}:{timestamp}:{provider}:{revision}"
        return f"sent:{observation.asset.value}:{timestamp}:{provider}:{revision}:{metric}"

    def _put_license(self, observation: ProviderObservation) -> None:
        key = (
            f"license:{_safe_key_part(observation.provider)}:"
            f"{_safe_key_part(observation.provider_revision)}"
        )
        self._put_immutable(
            key,
            {
                "schema_version": 1,
                "provider": observation.provider,
                "provider_revision": observation.provider_revision,
                "terms_reference": observation.terms_reference,
                "license_status": observation.license_status,
            },
        )

    def _put_immutable(self, key: str, document: dict[str, object]) -> ImmutableStoreResult:
        encoded = canonical_json_bytes(document).decode("utf-8")
        record_id = hashlib.sha256(encoded.encode()).hexdigest()
        existing = self._store.get(key)
        if existing is not None:
            if existing != encoded:
                raise ImmutableResearchRecordConflict(
                    f"immutable research record already exists with different content: {key}"
                )
            return ImmutableStoreResult(key=key, record_id=record_id, deduplicated=True)
        self._store.put(key, encoded)
        return ImmutableStoreResult(key=key, record_id=record_id, deduplicated=False)

    @staticmethod
    def _load(encoded: str) -> dict[str, Any]:
        try:
            value = json.loads(encoded)
        except json.JSONDecodeError as exc:
            raise CorruptResearchRecord("research record is not valid JSON") from exc
        if not isinstance(value, dict):
            raise CorruptResearchRecord("research record must be an object")
        return cast(dict[str, Any], value)
