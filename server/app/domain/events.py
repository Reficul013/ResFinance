from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class DomainValidationError(ValueError):
    pass


def validate_identifier(name: str, value: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise DomainValidationError(f"{name} must be an opaque identifier")
    return value


@dataclass(frozen=True)
class AppendEventCommand:
    tenant_id: str
    actor_id: str
    command_type: str
    idempotency_key: str
    event_type: str
    aggregate_type: str
    aggregate_id: str
    expected_version: int
    payload: dict[str, Any]
    source_references: tuple[str, ...] = ()
    contract_receipt: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "tenant_id",
            "actor_id",
            "command_type",
            "idempotency_key",
            "event_type",
            "aggregate_type",
            "aggregate_id",
        ):
            validate_identifier(name, str(getattr(self, name)))
        if self.expected_version < 0:
            raise DomainValidationError("expected_version cannot be negative")
        for reference in self.source_references:
            validate_identifier("source_reference", reference)
        if self.contract_receipt is not None:
            validate_identifier("contract_receipt", self.contract_receipt)


@dataclass(frozen=True)
class DomainEvent:
    schema_version: int
    event_id: str
    event_type: str
    occurred_at_utc: datetime
    tenant_id: str
    actor_id: str
    aggregate_type: str
    aggregate_id: str
    aggregate_version: int
    idempotency_key_hash: str
    payload: dict[str, Any]
    payload_hash: str
    source_references: tuple[str, ...]
    contract_receipt: str | None

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise DomainValidationError("unsupported event schema version")
        if self.occurred_at_utc.tzinfo is None:
            raise DomainValidationError("event timestamp must be timezone-aware")
        if self.occurred_at_utc.utcoffset() != UTC.utcoffset(self.occurred_at_utc):
            raise DomainValidationError("event timestamp must be UTC")
        if self.aggregate_version < 1:
            raise DomainValidationError("aggregate_version must be positive")


@dataclass(frozen=True)
class AppendResult:
    event: DomainEvent
    deduplicated: bool
