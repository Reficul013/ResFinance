from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.milestone0.resdb_artifact_roundtrip import (
    deterministic_block,
    parse_get_value,
    round_trip,
    round_trip_file,
)


def test_deterministic_block_matches_existing_artifact_generator() -> None:
    payload = deterministic_block(7, 100)

    seed = hashlib.sha256(b"resfinance-m0:7").digest()
    assert payload == (seed * 4)[:100]


def test_parse_get_value() -> None:
    assert parse_get_value("get key = key-1 value = dmFsdWU=\n", "key-1") == "dmFsdWU="


def test_parse_get_value_rejects_missing_key() -> None:
    with pytest.raises(RuntimeError, match="did not return"):
        parse_get_value("get value fail\n", "key-1")


def test_round_trip_preserves_logical_chunks_over_smaller_transport_records() -> None:
    values: dict[str, str] = {}

    def fake_client(
        _executable: Path,
        _config: Path,
        command: str,
        key: str,
        value: str | None = None,
    ) -> str:
        if command == "set":
            assert value is not None
            values[key] = value
            return "ret = 0\n"
        return f"get key = {key} value = {values[key]}\n"

    with patch(
        "scripts.milestone0.resdb_artifact_roundtrip.run_client",
        side_effect=fake_client,
    ):
        result = round_trip(
            Path("client"),
            Path("config"),
            size_bytes=19,
            logical_chunk_size=8,
            transport_chunk_size=4,
            key_prefix="artifact",
        )

    assert result["identical"] is True
    assert result["logical_chunk_count"] == 3
    assert result["transport_chunk_count"] == 5
    assert "artifact.chunk.000000.segment.0001" in values
    assert "artifact.manifest" in values


def test_transport_chunk_size_must_divide_logical_chunk_size() -> None:
    with pytest.raises(ValueError, match="divisible"):
        round_trip(
            Path("client"),
            Path("config"),
            size_bytes=10,
            logical_chunk_size=8,
            transport_chunk_size=3,
            key_prefix="artifact",
        )


def test_file_round_trip_records_kind_and_content_hash(tmp_path: Path) -> None:
    source = tmp_path / "gdelt.csv"
    source.write_bytes(b"day,asset,count\n2020-04-10,BTC,1\n")
    values: dict[str, str] = {}

    def fake_client(
        _executable: Path,
        _config: Path,
        command: str,
        key: str,
        value: str | None = None,
    ) -> str:
        if command == "set":
            assert value is not None
            values[key] = value
            return "ret = 0\n"
        return f"get key = {key} value = {values[key]}\n"

    with patch(
        "scripts.milestone0.resdb_artifact_roundtrip.run_client",
        side_effect=fake_client,
    ):
        result = round_trip_file(
            Path("client"),
            Path("config"),
            input_path=source,
            logical_chunk_size=16,
            transport_chunk_size=8,
            key_prefix="resfinance.m0.gdelt.hash",
            artifact_kind="gdelt-gkg-daily-aggregate-csv",
        )

    assert result["identical"] is True
    assert result["artifact_kind"] == "gdelt-gkg-daily-aggregate-csv"
    assert result["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert "resfinance.m0.gdelt.hash.manifest" in values
