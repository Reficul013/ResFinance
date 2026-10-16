from __future__ import annotations

import base64
import hashlib
import json
import re
import zlib
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
_MANIFEST_CHUNK_BYTES = 48 * 1024


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
        result = self._put_run_manifest(key, stored_manifest)
        return PersistedResearchRun(
            run_id=run_id,
            manifest_key=key,
            artifact_hashes={
                name: hashlib.sha256(content).hexdigest() for name, content in artifacts.items()
            },
            deduplicated=result.deduplicated,
        )

    def run_manifest(self, run_id: str) -> dict[str, Any]:
        encoded = self._store.get(f"run:{_safe(run_id)}:manifest")
        if encoded is None:
            raise KeyError(run_id)
        value = _object(encoded)
        if value.get("storage") != "zlib-json-chunks-v1":
            return value
        chunks = value.get("chunks")
        if not isinstance(chunks, list) or not all(isinstance(item, dict) for item in chunks):
            raise ValueError("research manifest chunk index is invalid")
        compressed_parts: list[bytes] = []
        for expected_number, raw_item in enumerate(chunks):
            item = cast(dict[str, object], raw_item)
            if item.get("number") != expected_number:
                raise ValueError("research manifest chunks are not ordered")
            key = item.get("key")
            expected_hash = item.get("sha256")
            if not isinstance(key, str) or not isinstance(expected_hash, str):
                raise ValueError("research manifest chunk metadata is invalid")
            encoded_chunk = self._store.get(key)
            if encoded_chunk is None:
                raise ValueError("research manifest chunk is missing")
            chunk = base64.b64decode(encoded_chunk, validate=True)
            if hashlib.sha256(chunk).hexdigest() != expected_hash:
                raise ValueError("research manifest chunk checksum mismatch")
            compressed_parts.append(chunk)
        compressed = b"".join(compressed_parts)
        if hashlib.sha256(compressed).hexdigest() != value.get("compressed_sha256"):
            raise ValueError("research manifest compressed checksum mismatch")
        try:
            content = zlib.decompress(compressed)
        except zlib.error as exc:
            raise ValueError("research manifest decompression failed") from exc
        if hashlib.sha256(content).hexdigest() != value.get("manifest_sha256"):
            raise ValueError("research manifest checksum mismatch")
        manifest = json.loads(content)
        if not isinstance(manifest, dict) or manifest.get("run_id") != run_id:
            raise ValueError("research manifest content is invalid")
        return cast(dict[str, Any], manifest)

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

    def promotion_event(self, event_id: str) -> dict[str, Any]:
        encoded = self._store.get(f"promotion:forecast:{_safe(event_id)}")
        if encoded is None:
            raise KeyError(event_id)
        event = _object(encoded)
        if (
            event.get("event_id") != event_id
            or event.get("event_type") != "research.model-promoted"
        ):
            raise ValueError("forecast promotion event is invalid")
        return event

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

    def _put_run_manifest(self, key: str, document: Mapping[str, object]) -> ImmutableStoreResult:
        content = canonical_json_bytes(document)
        manifest_hash = hashlib.sha256(content).hexdigest()
        compressed = zlib.compress(content, level=9)
        run_id = _required_text(document, "run_id")
        chunks = [
            compressed[offset : offset + _MANIFEST_CHUNK_BYTES]
            for offset in range(0, len(compressed), _MANIFEST_CHUNK_BYTES)
        ]
        chunk_records = [
            {
                "number": number,
                "key": f"run-manifest-chunk:{_safe(run_id)}:{number:06d}",
                "sha256": hashlib.sha256(chunk).hexdigest(),
            }
            for number, chunk in enumerate(chunks)
        ]
        pointer = {
            "schema_version": 1,
            "run_id": run_id,
            "storage": "zlib-json-chunks-v1",
            "manifest_sha256": manifest_hash,
            "compressed_sha256": hashlib.sha256(compressed).hexdigest(),
            "size_bytes": len(content),
            "compressed_size_bytes": len(compressed),
            "chunks": chunk_records,
        }
        encoded_pointer = canonical_json_bytes(pointer).decode()
        existing = self._store.get(key)
        if existing is not None:
            if existing != encoded_pointer:
                raise ValueError(f"immutable research record conflict: {key}")
            return ImmutableStoreResult(key=key, record_id=manifest_hash, deduplicated=True)
        for chunk, record in zip(chunks, chunk_records, strict=True):
            chunk_key = cast(str, record["key"])
            self._store.put(chunk_key, base64.b64encode(chunk).decode("ascii"))
        self._store.put(key, encoded_pointer)
        return ImmutableStoreResult(key=key, record_id=manifest_hash, deduplicated=False)


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
