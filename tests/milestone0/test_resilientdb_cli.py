from __future__ import annotations

import pytest

from server.app.infrastructure.resilientdb_cli import (
    parse_get_response,
    parse_range_response,
    parse_versioned_range_response,
)


def test_parse_get_response_returns_value() -> None:
    assert parse_get_response("get key = key-1 value = payload\n", "key-1") == "payload"


def test_parse_get_response_treats_empty_value_as_missing() -> None:
    assert parse_get_response("get key = key-1 value = \n", "key-1") is None


def test_parse_get_response_rejects_unknown_output() -> None:
    with pytest.raises(RuntimeError, match="unexpected ResilientDB get response"):
        parse_get_response("unknown response\n", "key-1")


def test_parse_range_response_returns_each_json_value() -> None:
    output = (
        "getrange min key = idx:a, max key = idx:a~\n"
        ' value = [{"event_key":"evt:1"},{"event_key":"evt:2"}]\n'
    )

    assert parse_range_response(output) == [
        '{"event_key":"evt:1"}',
        '{"event_key":"evt:2"}',
    ]


def test_parse_range_response_handles_empty_range() -> None:
    assert parse_range_response("getrange value fail, min key = a, max key = z\n") == []


def test_parse_versioned_range_response_decodes_protobuf_text() -> None:
    output = (
        "min key = idx:a max key = idx:a~\n"
        "getrange min key = idx:a, max key = idx:a~\n"
        ' value = item {\n  key: "idx:a:1"\n  value_info {\n'
        '    value: "{\\"event_key\\":\\"evt:1\\"}"\n    version: 2\n'
        "  }\n}\n"
    )

    assert parse_versioned_range_response(output) == ['{"event_key":"evt:1"}']
