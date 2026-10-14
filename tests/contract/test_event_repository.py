from __future__ import annotations

import base64
import hashlib
import json
import random
import zlib
from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from server.app.application.projections import rebuild_projection
from server.app.domain.events import AppendEventCommand
from server.app.infrastructure.blob_repository import EncryptedBlobRepository
from server.app.infrastructure.encryption import AesGcmCipher, canonical_json_bytes
from server.app.infrastructure.event_repository import (
    AggregateVersionConflict,
    EncryptedEventRepository,
    IdempotencyConflict,
)


class MemoryKeyValueStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def put(self, key: str, value: str) -> None:
        self.values[key] = value

    def range_values(self, prefix: str) -> Sequence[str]:
        return [self.values[key] for key in sorted(self.values) if key.startswith(prefix)]


def command(
    *, idempotency_key: str = "income-command-0001", expected_version: int = 0
) -> AppendEventCommand:
    return AppendEventCommand(
        tenant_id="tenant-001",
        actor_id="wallet-001",
        command_type="finance.record-income",
        idempotency_key=idempotency_key,
        event_type="finance.income-recorded",
        aggregate_type="finance-account",
        aggregate_id="account-001",
        expected_version=expected_version,
        payload={"minor_units": 125_00, "currency": "USD", "memo": "salary"},
        source_references=("source-001",),
    )


def repository(
    store: MemoryKeyValueStore,
) -> EncryptedEventRepository:
    return EncryptedEventRepository(
        store,
        AesGcmCipher(b"k" * 32, key_id="test-key-v1"),
        clock=lambda: datetime(2026, 10, 13, 12, 0, tzinfo=UTC),
    )


def test_write_read_rebuild_and_deduplicate_encrypted_events() -> None:
    store = MemoryKeyValueStore()
    events = repository(store)

    first = events.append(command())
    duplicate = events.append(command())
    second = events.append(
        AppendEventCommand(
            **{
                **command(
                    idempotency_key="expense-command-0002", expected_version=1
                ).__dict__,
                "event_type": "finance.expense-recorded",
                "payload": {
                    "minor_units": 25_00,
                    "currency": "USD",
                    "memo": "rent",
                },
            }
        )
    )

    assert not first.deduplicated
    assert duplicate.deduplicated
    assert duplicate.event.event_id == first.event.event_id
    assert second.event.aggregate_version == 2
    assert "salary" not in "".join(store.values.values())

    stream = events.load_stream(
        tenant_id="tenant-001",
        aggregate_type="finance-account",
        aggregate_id="account-001",
    )
    balance = rebuild_projection(
        stream,
        initial=0,
        reducer=lambda total, event: total
        + (
            int(event.payload["minor_units"])
            if event.event_type == "finance.income-recorded"
            else -int(event.payload["minor_units"])
        ),
    )
    assert balance == 100_00


def test_idempotency_key_reuse_with_different_command_is_rejected() -> None:
    store = MemoryKeyValueStore()
    events = repository(store)
    events.append(command())
    altered = AppendEventCommand(
        **{**command().__dict__, "payload": {"minor_units": 999, "currency": "USD"}}
    )

    with pytest.raises(IdempotencyConflict):
        events.append(altered)


def test_stale_aggregate_version_is_rejected() -> None:
    store = MemoryKeyValueStore()
    events = repository(store)
    events.append(command())

    with pytest.raises(AggregateVersionConflict):
        events.append(command(idempotency_key="another-command", expected_version=0))


def test_blob_round_trip_is_encrypted_chunked_and_deduplicated() -> None:
    store = MemoryKeyValueStore()
    blobs = EncryptedBlobRepository(
        store, AesGcmCipher(b"b" * 32, key_id="blob-test-key-v1")
    )
    content = random.Random(7).randbytes(600_000)

    first = blobs.put(content, media_type="application/octet-stream")
    duplicate = blobs.put(content, media_type="application/octet-stream")

    assert first.chunk_count >= 3
    assert duplicate.deduplicated
    assert blobs.get(first.sha256) == content
    assert content[:64].hex() not in "".join(store.values.values())

    manifest = json.loads(store.values[first.manifest_key])
    assert manifest["schema_version"] == 2
    assert manifest["logical_chunk_size"] == 256 * 1024
    assert manifest["transport_segment_size"] == 48 * 1024
    assert all(chunk["segments"] for chunk in manifest["chunks"])


def test_blob_repository_restores_legacy_unsegmented_schema() -> None:
    store = MemoryKeyValueStore()
    cipher = AesGcmCipher(b"l" * 32, key_id="legacy-blob-test-v1")
    blobs = EncryptedBlobRepository(store, cipher)
    content = b"legacy encrypted artifact"
    content_hash = hashlib.sha256(content).hexdigest()
    aad_document = {"sha256": content_hash, "media_type": "application/octet-stream"}
    envelope = cipher.encrypt_bytes(
        zlib.compress(content, level=9), aad=canonical_json_bytes(aad_document)
    )
    encrypted = canonical_json_bytes(envelope.to_dict())
    chunk_key = f"blob:{content_hash}:00000000"
    store.put(
        chunk_key,
        canonical_json_bytes(
            {
                "sha256": hashlib.sha256(encrypted).hexdigest(),
                "data_b64": base64.b64encode(encrypted).decode("ascii"),
            }
        ).decode(),
    )
    store.put(
        f"blob:{content_hash}:manifest",
        canonical_json_bytes(
            {
                "schema_version": 1,
                "sha256": content_hash,
                "size_bytes": len(content),
                "media_type": "application/octet-stream",
                "compression": "zlib-9",
                "encryption_aad": aad_document,
                "encrypted_size_bytes": len(encrypted),
                "logical_chunk_size": 256 * 1024,
                "chunks": [
                    {
                        "number": 0,
                        "key": chunk_key,
                        "sha256": hashlib.sha256(encrypted).hexdigest(),
                    }
                ],
            }
        ).decode(),
    )

    assert blobs.get(content_hash) == content
