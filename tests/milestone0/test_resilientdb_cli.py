from __future__ import annotations

import pytest

from server.app.infrastructure.resilientdb_cli import parse_get_response


def test_parse_get_response_returns_value() -> None:
    assert parse_get_response("get key = key-1 value = payload\n", "key-1") == "payload"


def test_parse_get_response_treats_empty_value_as_missing() -> None:
    assert parse_get_response("get key = key-1 value = \n", "key-1") is None


def test_parse_get_response_rejects_unknown_output() -> None:
    with pytest.raises(RuntimeError, match="unexpected ResilientDB get response"):
        parse_get_response("unknown response\n", "key-1")
