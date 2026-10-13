from __future__ import annotations

import argparse
import base64
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import cast


def deterministic_block(index: int, length: int) -> bytes:
    seed = hashlib.sha256(f"resfinance-m0:{index}".encode()).digest()
    repetitions = (length + len(seed) - 1) // len(seed)
    return (seed * repetitions)[:length]


def parse_get_value(output: str, key: str) -> str:
    prefix = f"get key = {key} value = "
    for line in output.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :]
    raise RuntimeError(f"ResilientDB get did not return key {key!r}")


def run_client(
    executable: Path,
    config: Path,
    command: str,
    key: str,
    value: str | None = None,
) -> str:
    args = [
        str(executable),
        "--config",
        str(config),
        "--cmd",
        command,
        "--key",
        key,
    ]
    if value is not None:
        args.extend(["--value", value])
    completed = subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"ResilientDB {command} failed for {key}: {completed.stderr.strip()}"
        )
    if command == "set" and "ret = 0" not in completed.stdout:
        raise RuntimeError(f"ResilientDB rejected {key}: {completed.stdout.strip()}")
    return completed.stdout


def restore(
    executable: Path,
    config: Path,
    *,
    key_prefix: str,
) -> dict[str, object]:
    manifest_key = f"{key_prefix}.manifest"
    encoded_manifest = parse_get_value(
        run_client(executable, config, "get", manifest_key), manifest_key
    )
    manifest = json.loads(encoded_manifest)
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise RuntimeError("unsupported artifact manifest")
    chunks = manifest.get("chunks")
    if not isinstance(chunks, list):
        raise RuntimeError("artifact manifest chunks must be a list")

    restored_hash = hashlib.sha256()
    restored_size = 0
    for raw_item in chunks:
        if not isinstance(raw_item, dict):
            raise RuntimeError("artifact manifest chunk must be an object")
        logical_index = raw_item.get("index")
        segment_count = raw_item.get("transport_segment_count")
        expected_size = raw_item.get("size_bytes")
        expected_hash = raw_item.get("sha256")
        if not all(
            (
                isinstance(logical_index, int),
                isinstance(segment_count, int),
                isinstance(expected_size, int),
                isinstance(expected_hash, str),
            )
        ):
            raise RuntimeError("artifact manifest chunk fields are invalid")
        logical_index = cast(int, logical_index)
        segment_count = cast(int, segment_count)
        expected_size = cast(int, expected_size)
        expected_hash = cast(str, expected_hash)
        parts: list[bytes] = []
        for segment_index in range(segment_count):
            key = (
                f"{key_prefix}.chunk.{logical_index:06d}"
                f".segment.{segment_index:04d}"
            )
            encoded = parse_get_value(run_client(executable, config, "get", key), key)
            parts.append(base64.b64decode(encoded, validate=True))
        payload = b"".join(parts)
        if hashlib.sha256(payload).hexdigest() != expected_hash:
            raise RuntimeError(f"logical chunk {logical_index} checksum mismatch")
        if len(payload) != expected_size:
            raise RuntimeError(f"logical chunk {logical_index} size mismatch")
        restored_hash.update(payload)
        restored_size += len(payload)
        if (logical_index + 1) % 25 == 0 or logical_index + 1 == len(chunks):
            print(
                f"restored {logical_index + 1}/{len(chunks)} logical chunks",
                file=sys.stderr,
            )

    source_sha256 = manifest.get("source_sha256")
    expected_total_size = manifest.get("size_bytes")
    if not isinstance(source_sha256, str) or not isinstance(expected_total_size, int):
        raise RuntimeError("artifact manifest totals are invalid")
    restored_sha256 = restored_hash.hexdigest()
    result = {
        "artifact_kind": manifest.get("artifact_kind"),
        "size_bytes": expected_total_size,
        "logical_chunk_size": manifest.get("logical_chunk_size"),
        "logical_chunk_count": len(chunks),
        "transport_chunk_size": manifest.get("transport_chunk_size"),
        "transport_chunk_count": manifest.get("transport_chunk_count"),
        "manifest_key": manifest_key,
        "source_sha256": source_sha256,
        "restored_sha256": restored_sha256,
        "identical": (
            restored_size == expected_total_size and restored_sha256 == source_sha256
        ),
    }
    if not result["identical"]:
        raise RuntimeError("restored artifact checksum or size differs")
    return result


def round_trip_file(
    executable: Path,
    config: Path,
    *,
    input_path: Path,
    logical_chunk_size: int,
    transport_chunk_size: int,
    key_prefix: str,
    artifact_kind: str,
) -> dict[str, object]:
    if logical_chunk_size <= 0 or transport_chunk_size <= 0:
        raise ValueError("chunk sizes must be positive")
    if logical_chunk_size % transport_chunk_size != 0:
        raise ValueError("logical chunk size must be divisible by transport chunk size")

    size_bytes = input_path.stat().st_size
    if size_bytes <= 0:
        raise ValueError("input file must not be empty")

    source_hash = hashlib.sha256()
    manifest_chunks: list[dict[str, object]] = []
    transport_chunk_count = 0
    with input_path.open("rb") as source:
        for logical_index, payload in enumerate(
            iter(lambda: source.read(logical_chunk_size), b"")
        ):
            source_hash.update(payload)
            segment_count = (
                len(payload) + transport_chunk_size - 1
            ) // transport_chunk_size
            for segment_index in range(segment_count):
                start = segment_index * transport_chunk_size
                segment = payload[start : start + transport_chunk_size]
                encoded = base64.b64encode(segment).decode("ascii")
                key = (
                    f"{key_prefix}.chunk.{logical_index:06d}"
                    f".segment.{segment_index:04d}"
                )
                run_client(executable, config, "set", key, encoded)
                transport_chunk_count += 1
            manifest_chunks.append(
                {
                    "index": logical_index,
                    "size_bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "transport_segment_count": segment_count,
                }
            )

    manifest = {
        "schema_version": 1,
        "artifact_kind": artifact_kind,
        "size_bytes": size_bytes,
        "logical_chunk_size": logical_chunk_size,
        "logical_chunk_count": len(manifest_chunks),
        "transport_chunk_size": transport_chunk_size,
        "transport_chunk_count": transport_chunk_count,
        "chunks": manifest_chunks,
        "source_sha256": source_hash.hexdigest(),
    }
    run_client(
        executable,
        config,
        "set",
        f"{key_prefix}.manifest",
        json.dumps(manifest, separators=(",", ":")),
    )
    return restore(executable, config, key_prefix=key_prefix)


def round_trip(
    executable: Path,
    config: Path,
    *,
    size_bytes: int,
    logical_chunk_size: int,
    transport_chunk_size: int,
    key_prefix: str,
) -> dict[str, object]:
    if size_bytes <= 0 or logical_chunk_size <= 0 or transport_chunk_size <= 0:
        raise ValueError("size and chunk sizes must be positive")
    if logical_chunk_size % transport_chunk_size != 0:
        raise ValueError("logical chunk size must be divisible by transport chunk size")

    logical_chunk_count = (size_bytes + logical_chunk_size - 1) // logical_chunk_size
    source_hash = hashlib.sha256()
    manifest_chunks: list[dict[str, object]] = []
    transport_chunk_count = 0

    remaining = size_bytes
    for logical_index in range(logical_chunk_count):
        length = min(logical_chunk_size, remaining)
        payload = deterministic_block(logical_index, length)
        source_hash.update(payload)
        segment_count = (length + transport_chunk_size - 1) // transport_chunk_size
        for segment_index in range(segment_count):
            start = segment_index * transport_chunk_size
            segment = payload[start : start + transport_chunk_size]
            encoded = base64.b64encode(segment).decode("ascii")
            key = (
                f"{key_prefix}.chunk.{logical_index:06d}"
                f".segment.{segment_index:04d}"
            )
            run_client(executable, config, "set", key, encoded)
            transport_chunk_count += 1
        manifest_chunks.append(
            {
                "index": logical_index,
                "size_bytes": length,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "transport_segment_count": segment_count,
            }
        )
        remaining -= length
        if (logical_index + 1) % 25 == 0 or logical_index + 1 == logical_chunk_count:
            print(
                f"stored {logical_index + 1}/{logical_chunk_count} logical chunks",
                file=sys.stderr,
            )

    manifest = {
        "schema_version": 1,
        "size_bytes": size_bytes,
        "logical_chunk_size": logical_chunk_size,
        "logical_chunk_count": logical_chunk_count,
        "transport_chunk_size": transport_chunk_size,
        "transport_chunk_count": transport_chunk_count,
        "chunks": manifest_chunks,
        "source_sha256": source_hash.hexdigest(),
    }
    run_client(
        executable,
        config,
        "set",
        f"{key_prefix}.manifest",
        json.dumps(manifest, separators=(",", ":")),
    )

    result = restore(executable, config, key_prefix=key_prefix)
    if result["source_sha256"] != source_hash.hexdigest():
        raise RuntimeError("stored artifact checksum differs from generated source")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Round-trip a deterministic artifact through real ResilientDB KV."
    )
    parser.add_argument("--client", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--size-mib", type=int, default=100)
    parser.add_argument("--logical-chunk-kib", type=int, default=256)
    parser.add_argument("--transport-chunk-kib", type=int, default=64)
    parser.add_argument("--key-prefix", default="resfinance.m0.artifact.v1")
    parser.add_argument(
        "--input",
        type=Path,
        help="store and verify this file instead of generating a deterministic artifact",
    )
    parser.add_argument(
        "--artifact-kind",
        default="generic-file",
        help="non-sensitive artifact type recorded in a file manifest",
    )
    parser.add_argument(
        "--restore-only",
        action="store_true",
        help="read and verify an existing manifest without rewriting records",
    )
    args = parser.parse_args()
    if args.restore_only:
        result = restore(args.client, args.config, key_prefix=args.key_prefix)
    elif args.input:
        result = round_trip_file(
            args.client,
            args.config,
            input_path=args.input,
            logical_chunk_size=args.logical_chunk_kib * 1024,
            transport_chunk_size=args.transport_chunk_kib * 1024,
            key_prefix=args.key_prefix,
            artifact_kind=args.artifact_kind,
        )
    else:
        result = round_trip(
            args.client,
            args.config,
            size_bytes=args.size_mib * 1024 * 1024,
            logical_chunk_size=args.logical_chunk_kib * 1024,
            transport_chunk_size=args.transport_chunk_kib * 1024,
            key_prefix=args.key_prefix,
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
