from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, cast

from server.app.application.ports import ImmutableStoreResult, KeyValueStore
from server.app.infrastructure.encryption import canonical_json_bytes
from server.app.infrastructure.research_repository import (
    PROSPECTIVE_GATE,
    PROSPECTIVE_GATE_KEY_PREFIX,
    ResearchRunRepository,
)

ENTRY_KEY_PREFIX = "prospective-entry:"
ISSUE_WINDOW = timedelta(hours=24)
_ASSETS = ("BTC", "ETH", "SOL")
_MODELS = ("deployable", "no-change")


class ProspectiveLedgerRepository:
    """Immutable protocol-v3 forecasts, one per decision date, and one gate decision per run.

    An entry is accepted only if it was issued after its run was frozen and no later than 24
    hours after its decision time, so every scored forecast predates its outcome.
    """

    def __init__(self, store: KeyValueStore, research_runs: ResearchRunRepository) -> None:
        self._store = store
        self._research_runs = research_runs

    def put_entry(self, entry: Mapping[str, object]) -> ImmutableStoreResult:
        run_id = str(entry.get("run_id", ""))
        _verify_entry(entry, self._frozen_manifest(run_id))
        key = _entry_key(run_id, str(entry["decision_date"]))
        encoded = canonical_json_bytes(entry).decode()
        existing = self._store.get(key)
        if existing is not None:
            if existing != encoded:
                raise ValueError(
                    "a prospective forecast is already recorded for this decision date"
                )
            return ImmutableStoreResult(
                key=key, record_id=str(entry["entry_hash"]), deduplicated=True
            )
        self._store.put(key, encoded)
        return ImmutableStoreResult(key=key, record_id=str(entry["entry_hash"]), deduplicated=False)

    def has_entry(self, run_id: str, decision_date: date) -> bool:
        return self._store.get(_entry_key(run_id, decision_date.isoformat())) is not None

    def entries(self, run_id: str) -> list[dict[str, Any]]:
        values = [_object(item) for item in self._store.range_values(_entry_key(run_id, ""))]
        for value in values:
            if value.get("run_id") != run_id or value.get("entry_hash") != _hash(
                value, "entry_hash"
            ):
                raise ValueError("prospective ledger entry is corrupt")
        return sorted(values, key=lambda value: str(value["decision_date"]))

    def put_gate_decision(self, decision: Mapping[str, object]) -> ImmutableStoreResult:
        run_id = str(decision.get("run_id", ""))
        self._frozen_manifest(run_id)
        criteria = decision.get("criteria")
        if (
            decision.get("decision_hash") != _hash(decision, "decision_hash")
            or decision.get("status") not in ("passed", "failed")
            or not isinstance(criteria, dict)
            or criteria.get("version") != PROSPECTIVE_GATE
        ):
            raise ValueError("prospective gate decision is invalid")
        stored = {str(entry["entry_hash"]) for entry in self.entries(run_id)}
        scored = decision.get("entry_hashes")
        if not isinstance(scored, list) or not scored or not set(scored) <= stored:
            raise ValueError("prospective gate decision scores entries absent from the ledger")
        key = f"{PROSPECTIVE_GATE_KEY_PREFIX}{_safe(run_id)}"
        encoded = canonical_json_bytes(decision).decode()
        existing = self._store.get(key)
        if existing is not None:
            if existing != encoded:
                raise ValueError("a different prospective gate decision is already recorded")
            return ImmutableStoreResult(
                key=key, record_id=str(decision["decision_hash"]), deduplicated=True
            )
        self._store.put(key, encoded)
        return ImmutableStoreResult(
            key=key, record_id=str(decision["decision_hash"]), deduplicated=False
        )

    def gate_decision(self, run_id: str) -> dict[str, Any] | None:
        encoded = self._store.get(f"{PROSPECTIVE_GATE_KEY_PREFIX}{_safe(run_id)}")
        return None if encoded is None else _object(encoded)

    def _frozen_manifest(self, run_id: str) -> dict[str, Any]:
        if not run_id:
            raise ValueError("prospective records require a run id")
        manifest = self._research_runs.run_manifest(run_id)
        if manifest.get("schema_version") != 4:
            raise ValueError("prospective records require a schema-v4 research run")
        return manifest


def _verify_entry(entry: Mapping[str, object], manifest: Mapping[str, object]) -> None:
    if entry.get("entry_hash") != _hash(entry, "entry_hash"):
        raise ValueError("prospective ledger entry hash does not match its content")
    window = cast(dict[str, object], manifest["prospective"])
    artifacts = cast(dict[str, str], manifest["artifact_hashes"])
    expected_hashes = {
        "deployment": artifacts[str(manifest["deployment_model_artifact"])],
        "fallback": artifacts[str(manifest["fallback_model_artifact"])],
    }
    if (
        entry.get("protocol") != manifest.get("evaluation_protocol")
        or entry.get("horizons") != window.get("horizons")
        or entry.get("model_hashes") != expected_hashes
        or entry.get("calibration_hash") != artifacts.get("adaptive-calibration.json")
    ):
        raise ValueError("prospective ledger entry does not match its frozen run")
    decision_date = date.fromisoformat(str(entry["decision_date"]))
    decision_time = _utc(str(entry["decision_time_utc"]))
    issued = _utc(str(entry["issued_at_utc"]))
    if decision_time != datetime.combine(decision_date + timedelta(days=1), time.min, tzinfo=UTC):
        raise ValueError("decision time must be 00:00 UTC on the day after the decision date")
    if decision_date < date.fromisoformat(str(window["prospective_start"])):
        raise ValueError("decision date precedes the prospective window")
    if issued < _utc(str(manifest["completed_at_utc"])):
        raise ValueError("forecast was issued before the model was frozen")
    if issued < decision_time:
        raise ValueError("forecast was issued before its decision time")
    if issued > decision_time + ISSUE_WINDOW:
        raise ValueError("late forecast cannot enter the prospective ledger")
    horizons = cast(list[int], window["horizons"])
    forecasts = entry.get("forecasts")
    cells = (
        {(item.get("model"), item.get("asset"), item.get("horizon_days")) for item in forecasts}
        if isinstance(forecasts, list) and all(isinstance(item, dict) for item in forecasts)
        else set()
    )
    expected = {
        (model, asset, horizon) for model in _MODELS for asset in _ASSETS for horizon in horizons
    }
    if cells != expected or len(cast(list[object], forecasts)) != len(expected):
        raise ValueError("prospective ledger entry must hold both forecasts for every cell")


def _entry_key(run_id: str, decision_date: str) -> str:
    return f"{ENTRY_KEY_PREFIX}{_safe(run_id)}:{decision_date}"


def _hash(document: Mapping[str, object], field: str) -> str:
    core = {key: value for key, value in document.items() if key != field}
    return hashlib.sha256(canonical_json_bytes(core)).hexdigest()


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("prospective timestamps must include a timezone")
    return parsed.astimezone(UTC)


def _safe(value: str) -> str:
    return value.replace(":", "-").replace("/", "-")


def _object(encoded: str) -> dict[str, Any]:
    value = json.loads(encoded)
    if not isinstance(value, dict):
        raise ValueError("prospective record must be an object")
    return cast(dict[str, Any], value)
