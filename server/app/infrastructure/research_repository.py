from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from server.app.application.ports import ImmutableStoreResult, KeyValueStore
from server.app.infrastructure.blob_repository import EncryptedBlobRepository
from server.app.infrastructure.encryption import canonical_json_bytes

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_MODELS = {
    "naive-zero-return",
    "linear-ridge",
    "lstm-sequence",
    "market-only",
    "fixed-equal-fusion",
    "adaptive-gating",
    "without-market",
    "without-sentiment",
    "without-on-chain",
}


@dataclass(frozen=True)
class PersistedResearchRun:
    run_id: str
    manifest_key: str
    artifact_hashes: dict[str, str]
    deduplicated: bool


@dataclass(frozen=True)
class PromotionCriteria:
    version: str = "forecast-promotion-v1"
    maximum_mae_ratio_to_naive: float = 1.0
    minimum_interval_coverage: float = 0.70

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("promotion criteria version is required")
        if self.maximum_mae_ratio_to_naive <= 0:
            raise ValueError("maximum MAE ratio must be positive")
        if not 0 <= self.minimum_interval_coverage <= 1:
            raise ValueError("minimum interval coverage must be between zero and one")


class ResearchRunRepository:
    def __init__(self, store: KeyValueStore, blobs: EncryptedBlobRepository) -> None:
        self._store = store
        self._blobs = blobs

    def put_completed_run(
        self,
        manifest: Mapping[str, object],
        artifacts: Mapping[str, bytes],
    ) -> PersistedResearchRun:
        run_id = _required_text(manifest, "run_id")
        _validate_manifest(manifest)
        expected_hashes = manifest.get("artifact_hashes")
        if not isinstance(expected_hashes, dict) or set(expected_hashes) != set(artifacts):
            raise ValueError("run artifacts must exactly match the manifest")
        if hashlib.sha256(artifacts["predictions.json"]).hexdigest() != manifest.get(
            "prediction_hash"
        ):
            raise ValueError("prediction artifact does not match the run prediction hash")
        if json.loads(artifacts["metrics.json"]) != manifest.get("metrics"):
            raise ValueError("metrics artifact does not match the run manifest")
        if json.loads(artifacts["gate-weights.json"]) != manifest.get("gate_weights"):
            raise ValueError("gate-weight artifact does not match the run manifest")
        artifact_records: dict[str, object] = {}
        for name, content in sorted(artifacts.items()):
            digest = hashlib.sha256(content).hexdigest()
            if expected_hashes.get(name) != digest:
                raise ValueError(f"artifact hash mismatch: {name}")
            receipt = self._blobs.put(
                content,
                media_type=_media_type(name),
                producing_run_id=run_id,
            )
            artifact_records[name] = {
                "sha256": receipt.sha256,
                "manifest_key": receipt.manifest_key,
                "size_bytes": receipt.size_bytes,
                "chunk_count": receipt.chunk_count,
            }
        stored_manifest = {**manifest, "persisted_artifacts": artifact_records}
        key = f"run:{_safe(run_id)}:manifest"
        result = self._put_immutable(key, stored_manifest)
        return PersistedResearchRun(
            run_id=run_id,
            manifest_key=key,
            artifact_hashes={
                name: hashlib.sha256(content).hexdigest()
                for name, content in artifacts.items()
            },
            deduplicated=result.deduplicated,
        )

    def run_manifest(self, run_id: str) -> dict[str, Any]:
        encoded = self._store.get(f"run:{_safe(run_id)}:manifest")
        if encoded is None:
            raise KeyError(run_id)
        return _object(encoded)

    def restore_artifact(self, run_id: str, name: str) -> bytes:
        manifest = self.run_manifest(run_id)
        records = manifest.get("persisted_artifacts")
        if not isinstance(records, dict) or not isinstance(records.get(name), dict):
            raise KeyError(name)
        digest = records[name].get("sha256")
        if not isinstance(digest, str):
            raise ValueError("persisted artifact digest is invalid")
        content = self._blobs.get(digest)
        if hashlib.sha256(content).hexdigest() != digest:
            raise ValueError("restored research artifact hash mismatch")
        return content

    def promote_model(
        self,
        *,
        run_id: str,
        model_name: str,
        criteria: PromotionCriteria,
        promoted_at_utc: datetime,
        approved_by: str,
    ) -> ImmutableStoreResult:
        if model_name != "adaptive-gating":
            raise ValueError("only the evaluated adaptive-gating candidate can be promoted")
        if not approved_by:
            raise ValueError("promotion requires an explicit approver")
        manifest = self.run_manifest(run_id)
        _validate_manifest(manifest)
        metrics = manifest.get("metrics")
        if not isinstance(metrics, dict):
            raise ValueError("run metrics are invalid")
        candidate = metrics.get(model_name)
        naive = metrics.get("naive-zero-return")
        if not isinstance(candidate, dict) or not isinstance(naive, dict):
            raise ValueError("promotion metrics are incomplete")
        candidate_mae = _metric(candidate, "mae")
        naive_mae = _metric(naive, "mae")
        coverage = _metric(candidate, "interval_coverage")
        passed = {
            "required_comparisons_complete": manifest.get("required_comparisons_complete") is True,
            "mae_ratio": candidate_mae <= naive_mae * criteria.maximum_mae_ratio_to_naive,
            "interval_coverage": coverage >= criteria.minimum_interval_coverage,
            "artifact_hashes_present": bool(manifest.get("artifact_hashes")),
        }
        if not all(passed.values()):
            failed = ", ".join(name for name, value in passed.items() if not value)
            raise ValueError(f"model does not satisfy promotion criteria: {failed}")
        promoted = promoted_at_utc.astimezone(UTC)
        event_core: dict[str, object] = {
            "schema_version": 1,
            "event_type": "research.model-promoted",
            "run_id": run_id,
            "model_name": model_name,
            "criteria": dict(criteria.__dict__),
            "evaluated_metrics": {
                "candidate_mae": candidate_mae,
                "naive_mae": naive_mae,
                "candidate_interval_coverage": coverage,
            },
            "checks": passed,
            "approved_by": approved_by,
            "promoted_at_utc": promoted.isoformat().replace("+00:00", "Z"),
        }
        event_id = hashlib.sha256(canonical_json_bytes(event_core)).hexdigest()
        return self._put_immutable(
            f"promotion:forecast:{event_id}", {**event_core, "event_id": event_id}
        )

    def _put_immutable(self, key: str, document: Mapping[str, object]) -> ImmutableStoreResult:
        encoded = canonical_json_bytes(document).decode()
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        existing = self._store.get(key)
        if existing is not None:
            if existing != encoded:
                raise ValueError(f"immutable research record conflict: {key}")
            return ImmutableStoreResult(key=key, record_id=digest, deduplicated=True)
        self._store.put(key, encoded)
        return ImmutableStoreResult(key=key, record_id=digest, deduplicated=False)


def _validate_manifest(manifest: Mapping[str, object]) -> None:
    if manifest.get("schema_version") != 1 or manifest.get("status") != "completed":
        raise ValueError("only completed schema-v1 research runs may be persisted")
    if manifest.get("assets") != ["BTC", "ETH", "SOL"]:
        raise ValueError("research run must contain exactly BTC, ETH, and SOL")
    reported = manifest.get("reported_models")
    if not isinstance(reported, list) or set(reported) != _REQUIRED_MODELS:
        raise ValueError("research run is missing a required baseline or ablation")
    if manifest.get("statistical_significance_claim") is not None:
        raise ValueError("unsubstantiated statistical significance claims are prohibited")
    folds = manifest.get("folds")
    if not isinstance(folds, list) or len(folds) != 5:
        raise ValueError("research run requires five walk-forward folds")
    for field in (
        "dataset_hash",
        "dataset_manifest_hash",
        "configuration_hash",
        "git_dirty_state_hash",
        "code_hash",
        "dependency_lock_hash",
        "prediction_hash",
    ):
        value = manifest.get(field)
        if not isinstance(value, str) or not _SHA256.fullmatch(value):
            raise ValueError(f"research manifest {field} must be a SHA-256 digest")
    for field in ("environment", "seeds", "determinism", "metrics", "artifact_hashes"):
        if not isinstance(manifest.get(field), dict):
            raise ValueError(f"research manifest {field} is required")


def _required_text(value: Mapping[str, object], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item:
        raise ValueError(f"{field} is required")
    return item


def _metric(metrics: dict[object, object], name: str) -> float:
    value = metrics.get(name)
    if not isinstance(value, int | float):
        raise ValueError(f"metric {name} is invalid")
    return float(value)


def _media_type(name: str) -> str:
    return "application/json" if name.endswith(".json") else "application/octet-stream"


def _safe(value: str) -> str:
    return value.replace(":", "-").replace("/", "-")


def _object(encoded: str) -> dict[str, Any]:
    value = json.loads(encoded)
    if not isinstance(value, dict):
        raise ValueError("research record must be an object")
    return cast(dict[str, Any], value)
