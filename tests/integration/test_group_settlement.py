from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from server.app.api.groups import CreateExpenseCommand
from server.app.application.finance import FinanceService
from server.app.application.groups import GroupRejected, GroupService, InjectedSagaCrash
from server.app.application.intents import base58_encode, canonical_json, parameters_hash
from server.app.domain.groups import (
    ContractConfirmation,
    ContractObligationState,
    ObligationStatus,
)
from server.app.domain.settlement import SignedIntent
from server.app.infrastructure.encryption import AesGcmCipher
from server.app.infrastructure.event_repository import EncryptedEventRepository
from tests.contract.test_authentication import MemoryKeyValueStore, wallet

NOW = datetime(2026, 10, 14, 17, 0, tzinfo=UTC)
ORIGIN = "https://app.resfinance.local"


class FakeSettlementContract:
    def __init__(self) -> None:
        self.obligations: dict[str, ContractObligationState] = {}
        self.balances: dict[str, int] = {}
        self.receipts: dict[str, ContractConfirmation] = {}
        self.used_intents: set[str] = set()
        self.used_nonces: set[str] = set()

    def create_obligation(
        self,
        *,
        operation_id: str,
        intent_hash: str,
        nonce_hash: str,
        creditor_address: str,
        debtor_address: str,
        amount_minor_units: int,
    ) -> ContractConfirmation:
        existing = self.obligations.get(operation_id)
        if existing is not None:
            return ContractConfirmation(
                receipt_id=f"receipt-{operation_id}",
                intent_hash=intent_hash,
                operation="create",
                amount_minor_units=existing.amount_minor_units,
                obligation_status=existing.status,
            )
        self.obligations[operation_id] = ContractObligationState(
            obligation_id=operation_id,
            creditor_address=creditor_address,
            debtor_address=debtor_address,
            amount_minor_units=amount_minor_units,
            settled_minor_units=0,
            status=ObligationStatus.PENDING,
        )
        return ContractConfirmation(
            receipt_id=f"receipt-{operation_id}",
            intent_hash=intent_hash,
            operation="create",
            amount_minor_units=amount_minor_units,
            obligation_status=ObligationStatus.PENDING,
        )

    def decide_obligation(
        self,
        *,
        intent_hash: str,
        nonce_hash: str,
        obligation_id: str,
        actor_address: str,
        approve: bool,
    ) -> ContractConfirmation:
        if intent_hash in self.receipts:
            return self.receipts[intent_hash]
        self._consume(intent_hash, nonce_hash)
        value = self.obligations[obligation_id]
        if value.debtor_address != actor_address or value.status != ObligationStatus.PENDING:
            raise RuntimeError("contract rejected decision")
        value = replace(
            value,
            status=ObligationStatus.OPEN if approve else ObligationStatus.REJECTED,
        )
        self.obligations[obligation_id] = value
        confirmation = ContractConfirmation(
            receipt_id=f"receipt-{intent_hash}",
            intent_hash=intent_hash,
            operation="approve" if approve else "reject",
            amount_minor_units=value.amount_minor_units,
            obligation_status=value.status,
            debtor_credit_balance=self.credit_balance(value.debtor_address),
            creditor_credit_balance=self.credit_balance(value.creditor_address),
        )
        self.receipts[intent_hash] = confirmation
        return confirmation

    def fund_credits(
        self,
        *,
        intent_hash: str,
        nonce_hash: str,
        actor_address: str,
        amount_minor_units: int,
    ) -> ContractConfirmation:
        if intent_hash in self.receipts:
            return self.receipts[intent_hash]
        self._consume(intent_hash, nonce_hash)
        self.balances[actor_address] = self.credit_balance(actor_address) + amount_minor_units
        confirmation = ContractConfirmation(
            receipt_id=f"receipt-{intent_hash}",
            intent_hash=intent_hash,
            operation="fund",
            amount_minor_units=amount_minor_units,
            debtor_credit_balance=self.credit_balance(actor_address),
            creditor_credit_balance=0,
        )
        self.receipts[intent_hash] = confirmation
        return confirmation

    def settle_obligation(
        self,
        *,
        intent_hash: str,
        nonce_hash: str,
        obligation_id: str,
        actor_address: str,
        amount_minor_units: int,
    ) -> ContractConfirmation:
        if intent_hash in self.receipts:
            return self.receipts[intent_hash]
        self._consume(intent_hash, nonce_hash)
        value = self.obligations[obligation_id]
        outstanding = value.amount_minor_units - value.settled_minor_units
        if (
            value.debtor_address != actor_address
            or value.status not in {ObligationStatus.OPEN, ObligationStatus.PARTIALLY_SETTLED}
            or amount_minor_units > outstanding
            or self.credit_balance(actor_address) < amount_minor_units
        ):
            raise RuntimeError("contract rejected settlement")
        self.balances[actor_address] -= amount_minor_units
        self.balances[value.creditor_address] = (
            self.credit_balance(value.creditor_address) + amount_minor_units
        )
        settled = value.settled_minor_units + amount_minor_units
        value = replace(
            value,
            settled_minor_units=settled,
            status=(
                ObligationStatus.SETTLED
                if settled == value.amount_minor_units
                else ObligationStatus.PARTIALLY_SETTLED
            ),
        )
        self.obligations[obligation_id] = value
        confirmation = ContractConfirmation(
            receipt_id=f"receipt-{intent_hash}",
            intent_hash=intent_hash,
            operation="settle",
            amount_minor_units=amount_minor_units,
            obligation_status=value.status,
            debtor_credit_balance=self.credit_balance(actor_address),
            creditor_credit_balance=self.credit_balance(value.creditor_address),
        )
        self.receipts[intent_hash] = confirmation
        return confirmation

    def receipt(self, intent_hash: str) -> ContractConfirmation | None:
        return self.receipts.get(intent_hash)

    def obligation(self, obligation_id: str) -> ContractObligationState:
        return self.obligations[obligation_id]

    def credit_balance(self, actor_address: str) -> int:
        return self.balances.get(actor_address, 0)

    def _consume(self, intent_hash: str, nonce_hash: str) -> None:
        if intent_hash in self.used_intents or nonce_hash in self.used_nonces:
            raise RuntimeError("contract replay")
        self.used_intents.add(intent_hash)
        self.used_nonces.add(nonce_hash)


def repository(store: MemoryKeyValueStore) -> EncryptedEventRepository:
    return EncryptedEventRepository(
        store,
        AesGcmCipher(b"g" * 32, key_id="groups-test-v1"),
        clock=lambda: NOW,
    )


def signed_intent(
    private_key: Ed25519PrivateKey,
    identity: Mapping[str, str],
    *,
    action: str,
    resource_id: str,
    parameters: Mapping[str, object],
    nonce: str,
) -> SignedIntent:
    payload: dict[str, object] = {
        "version": 1,
        "intent_id": f"intent-{nonce}",
        "action": action,
        "actor_public_key": identity["public_key"],
        "actor_address": identity["address"],
        "resource_id": resource_id,
        "parameters_hash": parameters_hash(parameters),
        "nonce": nonce,
        "issued_at": NOW.isoformat().replace("+00:00", "Z"),
        "expires_at": (NOW + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
        "origin": ORIGIN,
        "audience": "resfinance-api",
        "network_id": "pinned-local-network",
    }
    payload["signature"] = base58_encode(private_key.sign(canonical_json(payload)))
    return SignedIntent(
        version=1,
        intent_id=str(payload["intent_id"]),
        action=action,
        actor_public_key=identity["public_key"],
        actor_address=identity["address"],
        resource_id=resource_id,
        parameters_hash=str(payload["parameters_hash"]),
        nonce=nonce,
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
        origin=ORIGIN,
        audience="resfinance-api",
        network_id="pinned-local-network",
        signature=str(payload["signature"]),
    )


def expense_parameters(
    *, payer: str, debtor: str, expected_version: int = 2
) -> dict[str, object]:
    return {
        "group_id": "friends",
        "expense_id": "dinner",
        "payer_address": payer,
        "description": "Shared dinner",
        "amount_minor_units": 10_000,
        "occurred_on": "2026-10-14",
        "due_on": "2026-10-31",
        "shares": {payer: 4_000, debtor: 6_000},
        "expected_version": expected_version,
    }


def test_multi_user_partial_and_full_settlement_reconciles_after_crash() -> None:
    store = MemoryKeyValueStore()
    events = repository(store)
    finance = FinanceService(events)
    contract = FakeSettlementContract()
    payer_key, payer = wallet()
    debtor_key, debtor = wallet()
    service = GroupService(events, contract, finance, clock=lambda: NOW)

    service.create_group(
        actor_address=payer["address"],
        idempotency_key="create-friends",
        expected_version=0,
        group_id="friends",
        name="Friends",
        owner_display_name="Alex",
    )
    service.add_member(
        actor_address=payer["address"],
        idempotency_key="add-debtor",
        expected_version=1,
        group_id="friends",
        member_address=debtor["address"],
        display_name="Sam",
    )
    expense = expense_parameters(payer=payer["address"], debtor=debtor["address"])
    service.create_expense(
        actor_address=payer["address"],
        idempotency_key="expense-dinner",
        expected_version=2,
        group_id="friends",
        expense_id="dinner",
        payer_address=payer["address"],
        description="Shared dinner",
        amount_minor_units=10_000,
        occurred_on=date(2026, 10, 14),
        due_on=date(2026, 10, 31),
        shares={payer["address"]: 4_000, debtor["address"]: 6_000},
        intent=signed_intent(
            payer_key,
            payer,
            action="split.approve",
            resource_id="dinner",
            parameters=expense,
            nonce="nonce-expense-0000000001",
        ),
        origin=ORIGIN,
    )
    group = service.overview(actor_address=debtor["address"], group_id="friends")
    obligation = next(iter(group.obligations.values()))

    approval_parameters = {
        "group_id": "friends",
        "obligation_id": obligation.obligation_id,
        "decision": "approve",
        "expected_version": 3,
    }
    approval_intent = signed_intent(
        debtor_key,
        debtor,
        action="split.approve",
        resource_id=obligation.obligation_id,
        parameters=approval_parameters,
        nonce="nonce-approve-0000000001",
    )
    service.decide_obligation(
        actor_address=debtor["address"],
        idempotency_key="approve-dinner",
        expected_version=3,
        group_id="friends",
        obligation_id=obligation.obligation_id,
        approve=True,
        intent=approval_intent,
        origin=ORIGIN,
    )
    approval_retry = service.decide_obligation(
        actor_address=debtor["address"],
        idempotency_key="approve-dinner",
        expected_version=3,
        group_id="friends",
        obligation_id=obligation.obligation_id,
        approve=True,
        intent=approval_intent,
        origin=ORIGIN,
    )
    assert approval_retry.deduplicated
    debtor_finance = finance.overview(actor_address=debtor["address"], month="2026-10")
    payer_finance = finance.overview(actor_address=payer["address"], month="2026-10")
    assert debtor_finance.summary.payable_minor_units == 6_000
    assert payer_finance.summary.receivable_minor_units == 6_000

    fund_parameters = {
        "group_id": "friends",
        "amount_minor_units": 6_000,
        "expected_version": 4,
    }
    fund_intent = signed_intent(
        debtor_key,
        debtor,
        action="credits.fund",
        resource_id="friends",
        parameters=fund_parameters,
        nonce="nonce-fund-000000000001",
    )
    service.fund_credits(
        actor_address=debtor["address"],
        idempotency_key="fund-credits",
        expected_version=4,
        group_id="friends",
        amount_minor_units=6_000,
        intent=fund_intent,
        origin=ORIGIN,
    )
    fund_retry = service.fund_credits(
        actor_address=debtor["address"],
        idempotency_key="fund-credits",
        expected_version=4,
        group_id="friends",
        amount_minor_units=6_000,
        intent=fund_intent,
        origin=ORIGIN,
    )
    assert fund_retry.deduplicated
    partial_parameters = {
        "group_id": "friends",
        "obligation_id": obligation.obligation_id,
        "amount_minor_units": 2_000,
        "expected_version": 5,
    }
    service.settle_obligation(
        actor_address=debtor["address"],
        idempotency_key="settle-partial",
        expected_version=5,
        group_id="friends",
        obligation_id=obligation.obligation_id,
        amount_minor_units=2_000,
        intent=signed_intent(
            debtor_key,
            debtor,
            action="settlement.authorize",
            resource_id=obligation.obligation_id,
            parameters=partial_parameters,
            nonce="nonce-settle-0000000001",
        ),
        origin=ORIGIN,
    )
    after_partial = service.overview(
        actor_address=debtor["address"], group_id="friends"
    )
    partially_settled = after_partial.obligations[obligation.obligation_id]
    assert partially_settled.status == ObligationStatus.PARTIALLY_SETTLED
    assert partially_settled.outstanding_minor_units == 4_000

    full_parameters = {
        "group_id": "friends",
        "obligation_id": obligation.obligation_id,
        "amount_minor_units": 4_000,
        "expected_version": 7,
    }

    def crash(_: str) -> None:
        raise InjectedSagaCrash("contract committed before event propagation")

    crashing = GroupService(
        events, contract, finance, clock=lambda: NOW, after_contract=crash
    )
    with pytest.raises(InjectedSagaCrash):
        crashing.settle_obligation(
            actor_address=debtor["address"],
            idempotency_key="settle-full",
            expected_version=7,
            group_id="friends",
            obligation_id=obligation.obligation_id,
            amount_minor_units=4_000,
            intent=signed_intent(
                debtor_key,
                debtor,
                action="settlement.authorize",
                resource_id=obligation.obligation_id,
                parameters=full_parameters,
                nonce="nonce-settle-0000000002",
            ),
            origin=ORIGIN,
        )

    restarted = GroupService(events, contract, finance, clock=lambda: NOW)
    repaired = restarted.reconcile_group("friends")
    assert len(repaired) == 1
    final_group = restarted.overview(
        actor_address=debtor["address"], group_id="friends"
    )
    final_obligation = final_group.obligations[obligation.obligation_id]
    assert final_obligation.status == ObligationStatus.SETTLED
    assert final_obligation.outstanding_minor_units == 0
    assert final_group.credit_balances[debtor["address"]] == 0
    assert final_group.credit_balances[payer["address"]] == 6_000
    assert finance.overview(
        actor_address=debtor["address"], month="2026-10"
    ).summary.payable_minor_units == 0
    assert finance.overview(
        actor_address=payer["address"], month="2026-10"
    ).summary.receivable_minor_units == 0


def test_tamper_replay_overpayment_and_insufficient_credits_are_rejected() -> None:
    store = MemoryKeyValueStore()
    events = repository(store)
    contract = FakeSettlementContract()
    payer_key, payer = wallet()
    debtor_key, debtor = wallet()
    service = GroupService(events, contract, clock=lambda: NOW)
    service.create_group(
        actor_address=payer["address"],
        idempotency_key="create-friends",
        expected_version=0,
        group_id="friends",
        name="Friends",
        owner_display_name="Alex",
    )
    service.add_member(
        actor_address=payer["address"],
        idempotency_key="add-debtor",
        expected_version=1,
        group_id="friends",
        member_address=debtor["address"],
        display_name="Sam",
    )
    parameters = expense_parameters(payer=payer["address"], debtor=debtor["address"])
    intent = signed_intent(
        payer_key,
        payer,
        action="split.approve",
        resource_id="dinner",
        parameters=parameters,
        nonce="nonce-expense-0000000001",
    )
    with pytest.raises(GroupRejected, match="parameters hash mismatch"):
        service.create_expense(
            actor_address=payer["address"],
            idempotency_key="tampered-expense",
            expected_version=2,
            group_id="friends",
            expense_id="dinner",
            payer_address=payer["address"],
            description="Shared dinner",
            amount_minor_units=10_001,
            occurred_on=date(2026, 10, 14),
            due_on=date(2026, 10, 31),
            shares={payer["address"]: 4_001, debtor["address"]: 6_000},
            intent=intent,
            origin=ORIGIN,
        )
    assert contract.obligations == {}

    service.create_expense(
        actor_address=payer["address"],
        idempotency_key="expense-dinner",
        expected_version=2,
        group_id="friends",
        expense_id="dinner",
        payer_address=payer["address"],
        description="Shared dinner",
        amount_minor_units=10_000,
        occurred_on=date(2026, 10, 14),
        due_on=date(2026, 10, 31),
        shares={payer["address"]: 4_000, debtor["address"]: 6_000},
        intent=intent,
        origin=ORIGIN,
    )
    obligation = next(
        iter(
            service.overview(
                actor_address=debtor["address"], group_id="friends"
            ).obligations.values()
        )
    )
    approval_parameters = {
        "group_id": "friends",
        "obligation_id": obligation.obligation_id,
        "decision": "approve",
        "expected_version": 3,
    }
    approval_nonce = "nonce-approve-0000000001"
    service.decide_obligation(
        actor_address=debtor["address"],
        idempotency_key="approve-dinner",
        expected_version=3,
        group_id="friends",
        obligation_id=obligation.obligation_id,
        approve=True,
        intent=signed_intent(
            debtor_key,
            debtor,
            action="split.approve",
            resource_id=obligation.obligation_id,
            parameters=approval_parameters,
            nonce=approval_nonce,
        ),
        origin=ORIGIN,
    )

    overpayment_parameters = {
        "group_id": "friends",
        "obligation_id": obligation.obligation_id,
        "amount_minor_units": 6_001,
        "expected_version": 4,
    }
    with pytest.raises(GroupRejected, match="exceeds the outstanding"):
        service.settle_obligation(
            actor_address=debtor["address"],
            idempotency_key="overpayment",
            expected_version=4,
            group_id="friends",
            obligation_id=obligation.obligation_id,
            amount_minor_units=6_001,
            intent=signed_intent(
                debtor_key,
                debtor,
                action="settlement.authorize",
                resource_id=obligation.obligation_id,
                parameters=overpayment_parameters,
                nonce="nonce-overpayment-000001",
            ),
            origin=ORIGIN,
        )

    insufficient_parameters = {
        "group_id": "friends",
        "obligation_id": obligation.obligation_id,
        "amount_minor_units": 1,
        "expected_version": 4,
    }
    with pytest.raises(GroupRejected, match="insufficient non-redeemable credits"):
        service.settle_obligation(
            actor_address=debtor["address"],
            idempotency_key="insufficient",
            expected_version=4,
            group_id="friends",
            obligation_id=obligation.obligation_id,
            amount_minor_units=1,
            intent=signed_intent(
                debtor_key,
                debtor,
                action="settlement.authorize",
                resource_id=obligation.obligation_id,
                parameters=insufficient_parameters,
                nonce="nonce-insufficient-00001",
            ),
            origin=ORIGIN,
        )

    replay_parameters = {
        "group_id": "friends",
        "amount_minor_units": 100,
        "expected_version": 4,
    }
    with pytest.raises(GroupRejected, match="nonce was already used"):
        service.fund_credits(
            actor_address=debtor["address"],
            idempotency_key="replayed-nonce",
            expected_version=4,
            group_id="friends",
            amount_minor_units=100,
            intent=signed_intent(
                debtor_key,
                debtor,
                action="credits.fund",
                resource_id="friends",
                parameters=replay_parameters,
                nonce=approval_nonce,
            ),
            origin=ORIGIN,
        )
    assert contract.credit_balance(debtor["address"]) == 0


def test_contract_affecting_expense_command_requires_a_signed_intent() -> None:
    with pytest.raises(ValidationError, match="intent"):
        CreateExpenseCommand.model_validate(
            {
                "expense_id": "dinner",
                "payer_address": "0x" + "a" * 40,
                "description": "Shared dinner",
                "amount": {"currency": "USD", "minor_units": 1000},
                "occurred_on": "2026-10-14",
                "shares": {
                    "0x" + "a" * 40: {
                        "currency": "USD",
                        "minor_units": 1000,
                    }
                },
                "expected_version": 0,
            }
        )
