from __future__ import annotations

import base64
import hashlib
import json
import zlib
from dataclasses import dataclass
from typing import Any, cast

from server.app.application.ports import KeyValueStore
from server.app.infrastructure.encryption import (
    AesGcmCipher,
    EncryptionEnvelope,
    canonical_json_bytes,
)

LOGICAL_CHUNK_SIZE = 256 * 1024
TRANSPORT_SEGMENT_SIZE = 48 * 1024


@dataclass(frozen=True)
class BlobReceipt:
    sha256: str
    manifest_key: str
    size_bytes: int
    chunk_count: int
    deduplicated: bool


class EncryptedBlobRepository:
    def __init__(self, store: KeyValueStore, cipher: AesGcmCipher) -> None:
        self._store = store
        self._cipher = cipher

    def put(
        self,
        content: bytes,
        *,
        media_type: str,
        producing_run_id: str | None = None,
    ) -> BlobReceipt:
        content_hash = hashlib.sha256(content).hexdigest()
        manifest_key = f"blob:{content_hash}:manifest"
        existing = self._store.get(manifest_key)
        if existing is not None:
            restored, manifest = self._restore(existing)
            if restored != content:
                raise ValueError("existing content-addressed blob does not match")
            return BlobReceipt(
                sha256=content_hash,
                manifest_key=manifest_key,
                size_bytes=len(content),
                chunk_count=len(cast(list[object], manifest["chunks"])),
                deduplicated=True,
            )

        aad_document = {"sha256": content_hash, "media_type": media_type}
        compressed = zlib.compress(content, level=9)
        envelope = self._cipher.encrypt_bytes(
            compressed, aad=canonical_json_bytes(aad_document)
        )
        encrypted_bytes = canonical_json_bytes(envelope.to_dict())
        chunks = [
            encrypted_bytes[offset : offset + LOGICAL_CHUNK_SIZE]
            for offset in range(0, len(encrypted_bytes), LOGICAL_CHUNK_SIZE)
        ]
        chunk_records: list[dict[str, object]] = []
        for number, chunk in enumerate(chunks):
            chunk_hash = hashlib.sha256(chunk).hexdigest()
            segments = [
                chunk[offset : offset + TRANSPORT_SEGMENT_SIZE]
                for offset in range(0, len(chunk), TRANSPORT_SEGMENT_SIZE)
            ]
            segment_records: list[dict[str, object]] = []
            for segment_number, segment in enumerate(segments):
                segment_hash = hashlib.sha256(segment).hexdigest()
                segment_key = (
                    f"blob:{content_hash}:{number:08d}:segment:{segment_number:04d}"
                )
                self._store.put(
                    segment_key,
                    canonical_json_bytes(
                        {
                            "sha256": segment_hash,
                            "data_b64": base64.b64encode(segment).decode("ascii"),
                        }
                    ).decode("utf-8"),
                )
                segment_records.append(
                    {
                        "number": segment_number,
                        "key": segment_key,
                        "sha256": segment_hash,
                    }
                )
            chunk_records.append(
                {
                    "number": number,
                    "sha256": chunk_hash,
                    "size_bytes": len(chunk),
                    "segments": segment_records,
                }
            )
        manifest = {
            "schema_version": 2,
            "sha256": content_hash,
            "size_bytes": len(content),
            "media_type": media_type,
            "producing_run_id": producing_run_id,
            "compression": "zlib-9",
            "encryption_aad": aad_document,
            "encrypted_size_bytes": len(encrypted_bytes),
            "logical_chunk_size": LOGICAL_CHUNK_SIZE,
            "transport_segment_size": TRANSPORT_SEGMENT_SIZE,
            "chunks": chunk_records,
        }
        self._store.put(manifest_key, canonical_json_bytes(manifest).decode("utf-8"))
        return BlobReceipt(
            sha256=content_hash,
            manifest_key=manifest_key,
            size_bytes=len(content),
            chunk_count=len(chunks),
            deduplicated=False,
        )

    def get(self, sha256: str) -> bytes:
        manifest_key = f"blob:{sha256}:manifest"
        encoded = self._store.get(manifest_key)
        if encoded is None:
            raise KeyError(sha256)
        content, _ = self._restore(encoded)
        return content

    def _restore(self, encoded_manifest: str) -> tuple[bytes, dict[str, Any]]:
        manifest_value = json.loads(encoded_manifest)
        if not isinstance(manifest_value, dict):
            raise ValueError("blob manifest must be an object")
        manifest = cast(dict[str, Any], manifest_value)
        chunks_value = manifest.get("chunks")
        if not isinstance(chunks_value, list):
            raise ValueError("blob manifest chunks must be a list")
        encrypted_parts: list[bytes] = []
        for expected_number, item in enumerate(chunks_value):
            if not isinstance(item, dict) or item.get("number") != expected_number:
                raise ValueError("blob chunks are not ordered")
            expected_hash = item.get("sha256")
            if not isinstance(expected_hash, str):
                raise ValueError("blob chunk metadata is invalid")
            if isinstance(item.get("segments"), list):
                chunk = self._restore_segments(cast(list[object], item["segments"]))
            else:
                chunk = self._restore_legacy_chunk(item)
            if hashlib.sha256(chunk).hexdigest() != expected_hash:
                raise ValueError("blob chunk hash does not match")
            if "size_bytes" in item and len(chunk) != item["size_bytes"]:
                raise ValueError("blob logical chunk size does not match")
            encrypted_parts.append(chunk)
        envelope_value = json.loads(b"".join(encrypted_parts))
        aad = manifest.get("encryption_aad")
        if not isinstance(aad, dict):
            raise ValueError("blob encryption AAD is invalid")
        compressed = self._cipher.decrypt_bytes(
            EncryptionEnvelope.from_dict(envelope_value), aad=canonical_json_bytes(aad)
        )
        content = zlib.decompress(compressed)
        if len(content) != manifest.get("size_bytes"):
            raise ValueError("blob size does not match manifest")
        if hashlib.sha256(content).hexdigest() != manifest.get("sha256"):
            raise ValueError("blob aggregate hash does not match manifest")
        return content, manifest

    def _restore_segments(self, segments: list[object]) -> bytes:
        parts: list[bytes] = []
        for expected_number, item in enumerate(segments):
            if not isinstance(item, dict) or item.get("number") != expected_number:
                raise ValueError("blob transport segments are not ordered")
            key = item.get("key")
            expected_hash = item.get("sha256")
            if not isinstance(key, str) or not isinstance(expected_hash, str):
                raise ValueError("blob transport segment metadata is invalid")
            segment = self._load_chunk_record(key)
            if hashlib.sha256(segment).hexdigest() != expected_hash:
                raise ValueError("blob transport segment hash does not match")
            parts.append(segment)
        return b"".join(parts)

    def _restore_legacy_chunk(self, item: dict[str, Any]) -> bytes:
        key = item.get("key")
        if not isinstance(key, str):
            raise ValueError("legacy blob chunk key is invalid")
        return self._load_chunk_record(key)

    def _load_chunk_record(self, key: str) -> bytes:
        encoded = self._store.get(key)
        if encoded is None:
            raise ValueError(f"blob chunk is missing: {key}")
        record = json.loads(encoded)
        if not isinstance(record, dict) or not isinstance(record.get("data_b64"), str):
            raise ValueError("blob chunk record is invalid")
        return base64.b64decode(record["data_b64"], validate=True)
