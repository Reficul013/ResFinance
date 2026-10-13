from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any, cast

from server.app.application.ports import KeyValueStore
from server.app.domain.events import AppendEventCommand, AppendResult, DomainEvent
from server.app.infrastructure.encryption import (
    AesGcmCipher,
    EncryptionEnvelope,
    canonical_json_bytes,
)


class IdempotencyConflict(ValueError):
    pass


class AggregateVersionConflict(ValueError):
    pass


class CorruptEventError(ValueError):
    pass


class EncryptedEventRepository:
    def __init__(
        self,
        store: KeyValueStore,
        cipher: AesGcmCipher,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._cipher = cipher
        self._clock = clock

    def append(self, command: AppendEventCommand) -> AppendResult:
        command_document = {
            "tenant_id": command.tenant_id,
            "actor_id": command.actor_id,
            "command_type": command.command_type,
            "event_type": command.event_type,
            "aggregate_type": command.aggregate_type,
            "aggregate_id": command.aggregate_id,
            "expected_version": command.expected_version,
            "payload": command.payload,
            "source_references": list(command.source_references),
            "contract_receipt": command.contract_receipt,
        }
        command_hash = hashlib.sha256(canonical_json_bytes(command_document)).hexdigest()
        idempotency_hash = hashlib.sha256(command.idempotency_key.encode()).hexdigest()
        command_key = (
            f"cmd:{command.tenant_id}:{command.command_type}:{idempotency_hash}"
        )
        previous = self._store.get(command_key)
        if previous is not None:
            record = self._load_object(previous, "idempotency record")
            if record.get("command_hash") != command_hash:
                raise IdempotencyConflict(
                    "idempotency key was previously used for a different command"
                )
            event_key = record.get("event_key")
            if not isinstance(event_key, str):
                raise CorruptEventError("idempotency record has no event key")
            return AppendResult(event=self._load_event(event_key), deduplicated=True)

        stream = self.load_stream(
            tenant_id=command.tenant_id,
            aggregate_type=command.aggregate_type,
            aggregate_id=command.aggregate_id,
        )
        current_version = stream[-1].aggregate_version if stream else 0
        if current_version != command.expected_version:
            raise AggregateVersionConflict(
                f"expected aggregate version {command.expected_version}, "
                f"found {current_version}"
            )

        aggregate_version = current_version + 1
        event_id = "evt_" + hashlib.sha256(
            f"{command_key}:{command_hash}".encode()
        ).hexdigest()[:32]
        occurred_at = self._clock().astimezone(UTC)
        payload_hash = hashlib.sha256(canonical_json_bytes(command.payload)).hexdigest()
        metadata: dict[str, object] = {
            "schema_version": 1,
            "event_id": event_id,
            "event_type": command.event_type,
            "occurred_at_utc": occurred_at.isoformat().replace("+00:00", "Z"),
            "tenant_id": command.tenant_id,
            "actor_id": command.actor_id,
            "aggregate_type": command.aggregate_type,
            "aggregate_id": command.aggregate_id,
            "aggregate_version": aggregate_version,
            "idempotency_key_hash": idempotency_hash,
            "payload_hash": payload_hash,
            "source_references": list(command.source_references),
            "contract_receipt": command.contract_receipt,
        }
        envelope = self._cipher.encrypt_json(
            command.payload, aad=canonical_json_bytes(metadata)
        )
        stored_event = {**metadata, "encrypted_payload": envelope.to_dict()}
        timestamp_key = occurred_at.strftime("%Y%m%dT%H%M%S.%fZ")
        event_key = (
            f"evt:{command.tenant_id}:{command.event_type}:"
            f"{command.aggregate_id}:{timestamp_key}:{event_id}"
        )
        index_key = (
            f"idx:{command.tenant_id}:{command.aggregate_type}:"
            f"{command.aggregate_id}:{aggregate_version:020d}:{event_id}"
        )
        self._store.put(event_key, self._dump(stored_event))
        self._store.put(index_key, self._dump({"event_key": event_key}))
        self._store.put(
            command_key,
            self._dump(
                {
                    "schema_version": 1,
                    "command_hash": command_hash,
                    "event_id": event_id,
                    "event_key": event_key,
                }
            ),
        )
        return AppendResult(event=self._decode_event(stored_event), deduplicated=False)

    def load_stream(
        self, *, tenant_id: str, aggregate_type: str, aggregate_id: str
    ) -> list[DomainEvent]:
        prefix = f"idx:{tenant_id}:{aggregate_type}:{aggregate_id}:"
        index_values = self._store.range_values(prefix)
        event_keys: list[str] = []
        for encoded in index_values:
            index = self._load_object(encoded, "event index")
            event_key = index.get("event_key")
            if not isinstance(event_key, str):
                raise CorruptEventError("event index has no event key")
            event_keys.append(event_key)
        events = [self._load_event(key) for key in event_keys]
        events.sort(key=lambda event: event.aggregate_version)
        for expected, event in enumerate(events, start=1):
            if event.aggregate_version != expected:
                raise CorruptEventError("event stream versions are not contiguous")
        return events

    def _load_event(self, event_key: str) -> DomainEvent:
        encoded = self._store.get(event_key)
        if encoded is None:
            raise CorruptEventError(f"event is missing: {event_key}")
        return self._decode_event(self._load_object(encoded, "event"))

    def _decode_event(self, stored: dict[str, Any]) -> DomainEvent:
        encrypted = stored.get("encrypted_payload")
        metadata = {key: value for key, value in stored.items() if key != "encrypted_payload"}
        payload = self._cipher.decrypt_json(
            EncryptionEnvelope.from_dict(encrypted), aad=canonical_json_bytes(metadata)
        )
        payload_hash = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        if payload_hash != stored.get("payload_hash"):
            raise CorruptEventError("event payload hash does not match")
        source_references = stored.get("source_references")
        if not isinstance(source_references, list):
            raise CorruptEventError("source references must be a list")
        receipt = stored.get("contract_receipt")
        if receipt is not None and not isinstance(receipt, str):
            raise CorruptEventError("contract receipt must be a string")
        return DomainEvent(
            schema_version=int(stored["schema_version"]),
            event_id=str(stored["event_id"]),
            event_type=str(stored["event_type"]),
            occurred_at_utc=datetime.fromisoformat(
                str(stored["occurred_at_utc"]).replace("Z", "+00:00")
            ),
            tenant_id=str(stored["tenant_id"]),
            actor_id=str(stored["actor_id"]),
            aggregate_type=str(stored["aggregate_type"]),
            aggregate_id=str(stored["aggregate_id"]),
            aggregate_version=int(stored["aggregate_version"]),
            idempotency_key_hash=str(stored["idempotency_key_hash"]),
            payload=payload,
            payload_hash=payload_hash,
            source_references=tuple(str(value) for value in source_references),
            contract_receipt=receipt,
        )

    @staticmethod
    def _load_object(encoded: str, kind: str) -> dict[str, Any]:
        try:
            value = json.loads(encoded)
        except json.JSONDecodeError as exc:
            raise CorruptEventError(f"{kind} is not valid JSON") from exc
        if not isinstance(value, dict):
            raise CorruptEventError(f"{kind} must be an object")
        return cast(dict[str, Any], value)

    @staticmethod
    def _dump(value: object) -> str:
        return canonical_json_bytes(value).decode("utf-8")


def event_keys(events: Sequence[DomainEvent]) -> tuple[str, ...]:
    return tuple(event.event_id for event in events)
