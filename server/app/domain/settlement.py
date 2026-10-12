from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class SignedIntent:
    version: int
    intent_id: str
    action: str
    actor_public_key: str
    actor_address: str
    resource_id: str
    parameters_hash: str
    nonce: str
    issued_at: datetime
    expires_at: datetime
    audience: str
    network_id: str
    signature: str

    def unsigned_payload(self) -> dict[str, object]:
        return {
            "version": self.version,
            "intent_id": self.intent_id,
            "action": self.action,
            "actor_public_key": self.actor_public_key,
            "actor_address": self.actor_address,
            "resource_id": self.resource_id,
            "parameters_hash": self.parameters_hash,
            "nonce": self.nonce,
            "issued_at": self.issued_at.isoformat().replace("+00:00", "Z"),
            "expires_at": self.expires_at.isoformat().replace("+00:00", "Z"),
            "audience": self.audience,
            "network_id": self.network_id,
        }


@dataclass(frozen=True)
class SettlementParameters:
    credit_units: int
    expected_version: int

    def canonical_payload(self) -> dict[str, int]:
        return {
            "credit_units": self.credit_units,
            "expected_version": self.expected_version,
        }


@dataclass(frozen=True)
class ContractReceipt:
    contract_address: str
    intent_hash: str
    transaction_result: str
    confirmed_credit_units: int


@dataclass(frozen=True)
class SettlementResult:
    event_id: str
    projection_version: int
    occurred_at_utc: datetime
    receipt_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "projection_version": self.projection_version,
            "occurred_at_utc": self.occurred_at_utc.isoformat().replace("+00:00", "Z"),
            "receipt_ids": list(self.receipt_ids),
        }
