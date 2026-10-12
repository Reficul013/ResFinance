from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

import rfc8785
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from server.app.domain.settlement import (
    ContractReceipt,
    SettlementParameters,
    SettlementResult,
    SignedIntent,
)

BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


class SettlementRejected(ValueError):
    pass


class IdempotencyConflict(SettlementRejected):
    pass


class SettlementContract(Protocol):
    def settle(
        self,
        *,
        intent_hash: str,
        actor_address: str,
        nonce_hash: str,
        credit_units: int,
    ) -> ContractReceipt: ...


class SettlementEventStore(Protocol):
    def get(self, key: str) -> str | None: ...

    def put(self, key: str, value: str) -> None: ...


def base58_encode(value: bytes) -> str:
    leading_zeros = len(value) - len(value.lstrip(b"\0"))
    number = int.from_bytes(value)
    encoded = ""
    while number:
        number, remainder = divmod(number, 58)
        encoded = BASE58_ALPHABET[remainder] + encoded
    return "1" * leading_zeros + encoded


def base58_decode(value: str) -> bytes:
    number = 0
    for character in value:
        try:
            digit = BASE58_ALPHABET.index(character)
        except ValueError as exc:
            raise SettlementRejected("invalid base58 value") from exc
        number = number * 58 + digit
    decoded = number.to_bytes((number.bit_length() + 7) // 8, "big")
    leading_zeros = len(value) - len(value.lstrip("1"))
    return b"\0" * leading_zeros + decoded


def canonical_json(value: object) -> bytes:
    return rfc8785.dumps(value)  # type: ignore[arg-type]


def parameters_hash(parameters: SettlementParameters) -> str:
    return hashlib.sha256(canonical_json(parameters.canonical_payload())).hexdigest()


def actor_address(public_key: bytes) -> str:
    return "0x" + hashlib.sha256(public_key).digest()[-20:].hex()


def verify_intent(
    intent: SignedIntent,
    parameters: SettlementParameters,
    now: datetime,
) -> str:
    if intent.version != 1:
        raise SettlementRejected("unsupported intent version")
    if intent.action != "settlement.authorize":
        raise SettlementRejected("unexpected intent action")
    if intent.audience != "resfinance-api":
        raise SettlementRejected("unexpected intent audience")
    if intent.network_id != "pinned-local-network":
        raise SettlementRejected("unexpected intent network")
    if intent.issued_at.tzinfo is None or intent.expires_at.tzinfo is None:
        raise SettlementRejected("intent timestamps must include UTC offsets")
    normalized_now = now.astimezone(UTC)
    if intent.issued_at.astimezone(UTC) > normalized_now + timedelta(seconds=30):
        raise SettlementRejected("intent issued in the future")
    if intent.expires_at.astimezone(UTC) <= normalized_now:
        raise SettlementRejected("intent expired")
    if intent.expires_at - intent.issued_at > timedelta(minutes=10):
        raise SettlementRejected("intent lifetime exceeds ten minutes")
    if parameters.credit_units <= 0:
        raise SettlementRejected("credit units must be positive")
    if intent.parameters_hash != parameters_hash(parameters):
        raise SettlementRejected("intent parameters hash mismatch")

    public_key = base58_decode(intent.actor_public_key)
    if len(public_key) != 32:
        raise SettlementRejected("invalid Ed25519 public key length")
    if intent.actor_address != actor_address(public_key):
        raise SettlementRejected("actor address does not match public key")
    signature = base58_decode(intent.signature)
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(
            signature, canonical_json(intent.unsigned_payload())
        )
    except (InvalidSignature, ValueError) as exc:
        raise SettlementRejected("invalid intent signature") from exc
    return hashlib.sha256(canonical_json(intent.unsigned_payload())).hexdigest()


class SettlementService:
    def __init__(
        self,
        contract: SettlementContract,
        events: SettlementEventStore,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        allowed_origins: frozenset[str] = frozenset({"https://app.resfinance.local"}),
    ) -> None:
        self._contract = contract
        self._events = events
        self._clock = clock
        self._allowed_origins = allowed_origins

    def authorize(
        self,
        *,
        intent: SignedIntent,
        parameters: SettlementParameters,
        idempotency_key: str,
        origin: str,
    ) -> SettlementResult:
        if origin not in self._allowed_origins:
            raise SettlementRejected("origin is not allowed")
        if not idempotency_key or len(idempotency_key) > 128:
            raise SettlementRejected("invalid idempotency key")

        now = self._clock().astimezone(UTC)
        intent_hash = verify_intent(intent, parameters, now)
        command_hash = hashlib.sha256(
            canonical_json(
                {
                    "intent_hash": intent_hash,
                    "parameters": parameters.canonical_payload(),
                }
            )
        ).hexdigest()
        idempotency_store_key = f"idempotency:settlement:{idempotency_key}"
        previous = self._events.get(idempotency_store_key)
        if previous is not None:
            record = json.loads(previous)
            if record["command_hash"] != command_hash:
                raise IdempotencyConflict("idempotency key was reused")
            return _result_from_dict(record["result"])

        nonce_key = f"nonce:{intent.actor_address}:{intent.nonce}"
        if self._events.get(nonce_key) is not None:
            raise SettlementRejected("intent nonce was already used")

        receipt = self._contract.settle(
            intent_hash=intent_hash,
            actor_address=intent.actor_address,
            nonce_hash=hashlib.sha256(intent.nonce.encode()).hexdigest(),
            credit_units=parameters.credit_units,
        )
        if receipt.confirmed_credit_units != parameters.credit_units:
            raise SettlementRejected("contract confirmation mismatch")

        event_id = "evt_" + hashlib.sha256(intent.intent_id.encode()).hexdigest()[:24]
        result = SettlementResult(
            event_id=event_id,
            projection_version=parameters.expected_version + 1,
            occurred_at_utc=now,
            receipt_ids=(receipt.intent_hash,),
        )
        event = {
            "schema_version": 1,
            "event_id": event_id,
            "event_type": "settlement.confirmed",
            "resource_id": intent.resource_id,
            "actor_address": intent.actor_address,
            "credit_units": parameters.credit_units,
            "intent_hash": intent_hash,
            "contract_address": receipt.contract_address,
            "occurred_at_utc": result.to_dict()["occurred_at_utc"],
        }
        self._events.put(f"event:{event_id}", json.dumps(event, sort_keys=True))
        self._events.put(nonce_key, intent.intent_id)
        self._events.put(
            idempotency_store_key,
            json.dumps({"command_hash": command_hash, "result": result.to_dict()}),
        )
        return result


def _result_from_dict(value: dict[str, object]) -> SettlementResult:
    receipt_ids = value["receipt_ids"]
    if not isinstance(receipt_ids, list):
        raise ValueError("stored receipt IDs must be a list")
    return SettlementResult(
        event_id=str(value["event_id"]),
        projection_version=int(str(value["projection_version"])),
        occurred_at_utc=datetime.fromisoformat(
            str(value["occurred_at_utc"]).replace("Z", "+00:00")
        ),
        receipt_ids=tuple(str(item) for item in receipt_ids),
    )
