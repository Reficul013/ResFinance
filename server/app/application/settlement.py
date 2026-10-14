from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from server.app.application.intents import (
    IntentPolicy,
    IntentRejected,
    canonical_json,
    verify_signed_intent,
)
from server.app.application.intents import (
    parameters_hash as hash_parameters,
)
from server.app.domain.settlement import (
    ContractReceipt,
    SettlementParameters,
    SettlementResult,
    SignedIntent,
)


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


def parameters_hash(parameters: SettlementParameters) -> str:
    return hash_parameters(parameters.canonical_payload())


def verify_intent(
    intent: SignedIntent,
    parameters: SettlementParameters,
    now: datetime,
    origin: str = "https://app.resfinance.local",
) -> str:
    if parameters.credit_units <= 0:
        raise SettlementRejected("credit units must be positive")
    try:
        return verify_signed_intent(
            intent,
            parameters=parameters.canonical_payload(),
            origin=origin,
            now=now,
            policy=IntentPolicy(action="settlement.authorize"),
        )
    except IntentRejected as exc:
        raise SettlementRejected(str(exc)) from exc


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
        intent_hash = verify_intent(intent, parameters, now, origin)
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
