from __future__ import annotations

import hashlib
import json
from datetime import UTC
from typing import Any, cast

from server.app.application.ports import ImmutableStoreResult, KeyValueStore
from server.app.domain.portfolio import ForecastSnapshot
from server.app.infrastructure.encryption import canonical_json_bytes
from server.app.infrastructure.research_repository import ResearchRunRepository


class PortfolioResearchRepository:
    def __init__(self, store: KeyValueStore, research_runs: ResearchRunRepository) -> None:
        self._store = store
        self._research_runs = research_runs

    def put_forecast_snapshot(self, snapshot: ForecastSnapshot) -> ImmutableStoreResult:
        self._validate_promotion(snapshot)
        document = {**snapshot.to_dict(), "snapshot_id": snapshot.snapshot_id}
        timestamp = snapshot.as_of_utc.astimezone(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        key = f"forecast:{timestamp}:{snapshot.snapshot_id}"
        return self._put_immutable(key, document)

    def _validate_promotion(self, snapshot: ForecastSnapshot) -> None:
        promotion = self._research_runs.promotion_event(snapshot.promotion_event_id)
        if promotion.get("run_id") != snapshot.run_id:
            raise ValueError("forecast run does not match its promotion event")
        if promotion.get("model_name") != snapshot.model_name:
            raise ValueError("forecast model does not match its promotion event")
        promoted_model_hash = promotion.get("deployment_model_hash")
        if promoted_model_hash is not None and promoted_model_hash != snapshot.model_hash:
            raise ValueError("forecast model does not match the promoted deployment artifact")
        run = self._research_runs.run_manifest(snapshot.run_id)
        artifacts = run.get("artifact_hashes")
        if not isinstance(artifacts, dict) or snapshot.model_hash not in artifacts.values():
            raise ValueError("forecast model hash is absent from its research run")
        if run.get("dataset_hash") != snapshot.dataset_hash:
            raise ValueError("forecast dataset hash does not match its research run")

    def latest_forecast_snapshot(self) -> ForecastSnapshot | None:
        records = [self._load(value) for value in self._store.range_values("forecast:")]
        if not records:
            return None
        records.sort(key=lambda value: str(value.get("as_of_utc", "")))
        latest = records[-1]
        snapshot = ForecastSnapshot.from_dict(latest)
        if latest.get("snapshot_id") != snapshot.snapshot_id:
            raise ValueError("forecast snapshot content hash does not match")
        self._validate_promotion(snapshot)
        return snapshot

    def _put_immutable(self, key: str, document: dict[str, object]) -> ImmutableStoreResult:
        encoded = canonical_json_bytes(document).decode()
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        existing = self._store.get(key)
        if existing is not None:
            if existing != encoded:
                raise ValueError(f"immutable portfolio record conflict: {key}")
            return ImmutableStoreResult(key=key, record_id=digest, deduplicated=True)
        self._store.put(key, encoded)
        return ImmutableStoreResult(key=key, record_id=digest, deduplicated=False)

    @staticmethod
    def _load(encoded: str) -> dict[str, Any]:
        value = json.loads(encoded)
        if not isinstance(value, dict):
            raise ValueError("portfolio research record must be an object")
        return cast(dict[str, Any], value)
