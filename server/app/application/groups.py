from __future__ import annotations

import hashlib
import re
import threading
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Protocol

from server.app.application.finance import FinanceService
from server.app.application.intents import IntentPolicy, IntentRejected, verify_signed_intent
from server.app.application.projections import rebuild_projection
from server.app.domain.events import AppendEventCommand, AppendResult
from server.app.domain.finance import ObligationDirection
from server.app.domain.groups import (
    ContractConfirmation,
    ContractObligationState,
    GroupDirectory,
    GroupObligation,
    GroupProjection,
    ObligationStatus,
    reduce_group_directory,
    reduce_group_event,
)
from server.app.domain.settlement import SignedIntent
from server.app.infrastructure.event_repository import EncryptedEventRepository

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ADDRESS = re.compile(r"^0x[0-9a-f]{40}$")
_MAX_MONEY = 9_000_000_000_000_000


class GroupRejected(ValueError):
    pass


class InjectedSagaCrash(RuntimeError):
    pass


class SettlementContract(Protocol):
    def create_obligation(
        self,
        *,
        operation_id: str,
        intent_hash: str,
        nonce_hash: str,
        creditor_address: str,
        debtor_address: str,
        amount_minor_units: int,
    ) -> ContractConfirmation: ...

    def decide_obligation(
        self,
        *,
        intent_hash: str,
        nonce_hash: str,
        obligation_id: str,
        actor_address: str,
        approve: bool,
    ) -> ContractConfirmation: ...

    def fund_credits(
        self,
        *,
        intent_hash: str,
        nonce_hash: str,
        actor_address: str,
        amount_minor_units: int,
    ) -> ContractConfirmation: ...

    def settle_obligation(
        self,
        *,
        intent_hash: str,
        nonce_hash: str,
        obligation_id: str,
        actor_address: str,
        amount_minor_units: int,
    ) -> ContractConfirmation: ...

    def receipt(self, intent_hash: str) -> ContractConfirmation | None: ...

    def obligation(self, obligation_id: str) -> ContractObligationState: ...

    def credit_balance(self, actor_address: str) -> int: ...


class GroupService:
    def __init__(
        self,
        repository: EncryptedEventRepository,
        contract: SettlementContract,
        finance: FinanceService | None = None,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        allowed_origins: frozenset[str] = frozenset(
            {"https://app.resfinance.local", "http://127.0.0.1:5173"}
        ),
        after_contract: Callable[[str], None] | None = None,
    ) -> None:
        self._repository = repository
        self._contract = contract
        self._finance = finance
        self._clock = clock
        self._allowed_origins = allowed_origins
        self._after_contract = after_contract
        self._lock = threading.RLock()

    def create_group(
        self,
        *,
        actor_address: str,
        idempotency_key: str,
        expected_version: int,
        group_id: str,
        name: str,
        owner_display_name: str,
    ) -> AppendResult:
        actor_address = _address(actor_address)
        group_id = _identifier("group_id", group_id)
        name = _label("name", name, 80)
        owner_display_name = _label("owner_display_name", owner_display_name, 80)
        command = self._group_command(
            group_id=group_id,
            actor_address=actor_address,
            idempotency_key=idempotency_key,
            expected_version=expected_version,
            command_type="groups.create-group",
            event_type="group.created",
            payload={
                "group_id": group_id,
                "name": name,
                "owner_address": actor_address,
                "owner_display_name": owner_display_name,
            },
        )
        with self._lock:
            existing = self._repository.find_idempotent(command)
            if existing is not None:
                self._link_directory(actor_address, group_id)
                return existing
            if self._projection(group_id).group_id is not None:
                raise GroupRejected("group ID already exists")
            result = self._repository.append(command)
            self._link_directory(actor_address, group_id)
            return result

    def add_member(
        self,
        *,
        actor_address: str,
        idempotency_key: str,
        expected_version: int,
        group_id: str,
        member_address: str,
        display_name: str,
    ) -> AppendResult:
        group_id = _identifier("group_id", group_id)
        actor_address = _address(actor_address)
        member_address = _address(member_address)
        display_name = _label("display_name", display_name, 80)
        command = self._group_command(
            group_id=group_id,
            actor_address=actor_address,
            idempotency_key=idempotency_key,
            expected_version=expected_version,
            command_type="groups.add-member",
            event_type="group.member-added",
            payload={
                "actor_address": member_address,
                "display_name": display_name,
            },
        )
        with self._lock:
            existing = self._repository.find_idempotent(command)
            if existing is not None:
                self._link_directory(member_address, group_id)
                return existing
            projection = self._require_group(group_id)
            self._require_owner(projection, actor_address)
            self._require_version(projection, expected_version)
            if member_address in projection.members:
                raise GroupRejected("member already belongs to the group")
            result = self._repository.append(command)
            self._link_directory(member_address, group_id)
            return result

    def create_expense(
        self,
        *,
        actor_address: str,
        idempotency_key: str,
        expected_version: int,
        group_id: str,
        expense_id: str,
        payer_address: str,
        description: str,
        amount_minor_units: int,
        occurred_on: date,
        due_on: date | None,
        shares: Mapping[str, int],
        intent: SignedIntent,
        origin: str,
    ) -> AppendResult:
        group_id = _identifier("group_id", group_id)
        expense_id = _identifier("expense_id", expense_id)
        actor_address = _address(actor_address)
        payer_address = _address(payer_address)
        description = _label("description", description, 160)
        amount_minor_units = _money(amount_minor_units)
        normalized_shares = {
            _address(address): _money(amount) for address, amount in shares.items()
        }
        if sum(normalized_shares.values()) != amount_minor_units:
            raise GroupRejected("split shares must equal the expense amount exactly")
        parameters: dict[str, object] = {
            "group_id": group_id,
            "expense_id": expense_id,
            "payer_address": payer_address,
            "description": description,
            "amount_minor_units": amount_minor_units,
            "occurred_on": occurred_on.isoformat(),
            "due_on": due_on.isoformat() if due_on else None,
            "shares": dict(sorted(normalized_shares.items())),
            "expected_version": expected_version,
        }
        intent_hash, nonce_hash = self._verify_intent(
            intent,
            actor_address=actor_address,
            resource_id=expense_id,
            action="split.approve",
            parameters=parameters,
            origin=origin,
        )
        with self._lock:
            projection = self._require_group(group_id)
            existing_expense = projection.expenses.get(expense_id)
            if existing_expense is not None:
                existing_obligations = [
                    {
                        "obligation_id": obligation.obligation_id,
                        "creditor_address": obligation.creditor_address,
                        "debtor_address": obligation.debtor_address,
                        "amount_minor_units": obligation.amount_minor_units,
                        "due_on": obligation.due_on.isoformat()
                        if obligation.due_on
                        else None,
                    }
                    for obligation in (
                        projection.obligations[value]
                        for value in existing_expense.obligation_ids
                    )
                ]
                command = self._group_command(
                    group_id=group_id,
                    actor_address=actor_address,
                    idempotency_key=idempotency_key,
                    expected_version=expected_version,
                    command_type="groups.create-expense",
                    event_type="group.expense-created",
                    payload={
                        **parameters,
                        "obligations": existing_obligations,
                        "contract_receipts": list(
                            existing_expense.contract_receipts
                        ),
                        "intent_hash": intent_hash,
                        "nonce_hash": nonce_hash,
                    },
                    contract_receipt=(
                        existing_expense.contract_receipts[0]
                        if existing_expense.contract_receipts
                        else None
                    ),
                )
                existing = self._repository.find_idempotent(command)
                if existing is not None:
                    return existing
                raise GroupRejected("expense ID already exists")
            self._require_member(projection, actor_address)
            self._require_member(projection, payer_address)
            self._require_version(projection, expected_version)
            if payer_address != actor_address:
                raise GroupRejected("the signed actor must be the expense payer")
            for member in normalized_shares:
                self._require_member(projection, member)
            self._require_unused_nonce(projection, nonce_hash)

            obligations: list[dict[str, object]] = []
            receipts: list[str] = []
            for debtor, amount in sorted(normalized_shares.items()):
                if debtor == payer_address:
                    continue
                obligation_id = _derived_id("obl", expense_id, debtor)
                try:
                    confirmation = self._contract.create_obligation(
                        operation_id=obligation_id,
                        intent_hash=intent_hash,
                        nonce_hash=nonce_hash,
                        creditor_address=payer_address,
                        debtor_address=debtor,
                        amount_minor_units=amount,
                    )
                except RuntimeError as exc:
                    raise GroupRejected(str(exc)) from exc
                receipts.append(confirmation.receipt_id)
                obligations.append(
                    {
                        "obligation_id": obligation_id,
                        "creditor_address": payer_address,
                        "debtor_address": debtor,
                        "amount_minor_units": amount,
                        "due_on": due_on.isoformat() if due_on else None,
                    }
                )
            command = self._group_command(
                group_id=group_id,
                actor_address=actor_address,
                idempotency_key=idempotency_key,
                expected_version=expected_version,
                command_type="groups.create-expense",
                event_type="group.expense-created",
                payload={
                    **parameters,
                    "obligations": obligations,
                    "contract_receipts": receipts,
                    "intent_hash": intent_hash,
                    "nonce_hash": nonce_hash,
                },
                contract_receipt=receipts[0] if receipts else None,
            )
            existing = self._repository.find_idempotent(command)
            if existing is not None:
                return existing
            return self._repository.append(command)

    def decide_obligation(
        self,
        *,
        actor_address: str,
        idempotency_key: str,
        expected_version: int,
        group_id: str,
        obligation_id: str,
        approve: bool,
        intent: SignedIntent,
        origin: str,
    ) -> AppendResult:
        group_id = _identifier("group_id", group_id)
        obligation_id = _identifier("obligation_id", obligation_id)
        actor_address = _address(actor_address)
        parameters: dict[str, object] = {
            "group_id": group_id,
            "obligation_id": obligation_id,
            "decision": "approve" if approve else "reject",
            "expected_version": expected_version,
        }
        intent_hash, nonce_hash = self._verify_intent(
            intent,
            actor_address=actor_address,
            resource_id=obligation_id,
            action="split.approve",
            parameters=parameters,
            origin=origin,
        )
        with self._lock:
            projection = self._require_group(group_id)
            obligation = self._require_obligation(projection, obligation_id)
            source_event_id = projection.expenses[
                obligation.expense_id
            ].source_event_id
            confirmation = self._contract.receipt(intent_hash)
            if confirmation is not None:
                command = self._group_command(
                    group_id=group_id,
                    actor_address=actor_address,
                    idempotency_key=idempotency_key,
                    expected_version=expected_version,
                    command_type="groups.decide-obligation",
                    event_type=(
                        "group.obligation-approved"
                        if approve
                        else "group.obligation-rejected"
                    ),
                    payload={
                        **parameters,
                        "intent_hash": intent_hash,
                        "nonce_hash": nonce_hash,
                    },
                    source_references=(source_event_id,),
                    contract_receipt=confirmation.receipt_id,
                )
                existing = self._repository.find_idempotent(command)
                if existing is not None:
                    if approve:
                        self._propagate_open_obligation(group_id, obligation)
                    return existing
            self._require_version(projection, expected_version)
            if obligation.debtor_address != actor_address:
                raise GroupRejected("only the debtor may decide this obligation")
            if obligation.status != ObligationStatus.PENDING:
                raise GroupRejected("obligation is no longer pending")
            self._require_unused_nonce(projection, nonce_hash)
            try:
                confirmation = self._contract.decide_obligation(
                    intent_hash=intent_hash,
                    nonce_hash=nonce_hash,
                    obligation_id=obligation_id,
                    actor_address=actor_address,
                    approve=approve,
                )
            except RuntimeError as exc:
                raise GroupRejected(str(exc)) from exc
            result = self._repository.append(
                self._group_command(
                    group_id=group_id,
                    actor_address=actor_address,
                    idempotency_key=idempotency_key,
                    expected_version=expected_version,
                    command_type="groups.decide-obligation",
                    event_type=(
                        "group.obligation-approved"
                        if approve
                        else "group.obligation-rejected"
                    ),
                    payload={
                        **parameters,
                        "intent_hash": intent_hash,
                        "nonce_hash": nonce_hash,
                    },
                    source_references=(source_event_id,),
                    contract_receipt=confirmation.receipt_id,
                )
            )
            if approve:
                updated = self._require_group(group_id)
                self._propagate_open_obligation(
                    group_id,
                    self._require_obligation(updated, obligation_id),
                )
            return result

    def fund_credits(
        self,
        *,
        actor_address: str,
        idempotency_key: str,
        expected_version: int,
        group_id: str,
        amount_minor_units: int,
        intent: SignedIntent,
        origin: str,
    ) -> AppendResult:
        group_id = _identifier("group_id", group_id)
        actor_address = _address(actor_address)
        amount_minor_units = _money(amount_minor_units)
        parameters: dict[str, object] = {
            "group_id": group_id,
            "amount_minor_units": amount_minor_units,
            "expected_version": expected_version,
        }
        intent_hash, nonce_hash = self._verify_intent(
            intent,
            actor_address=actor_address,
            resource_id=group_id,
            action="credits.fund",
            parameters=parameters,
            origin=origin,
        )
        with self._lock:
            projection = self._require_group(group_id)
            self._require_member(projection, actor_address)
            confirmation = self._contract.receipt(intent_hash)
            if confirmation is not None:
                command = self._group_command(
                    group_id=group_id,
                    actor_address=actor_address,
                    idempotency_key=idempotency_key,
                    expected_version=expected_version,
                    command_type="groups.fund-credits",
                    event_type="group.credits-funded",
                    payload={
                        **parameters,
                        "actor_address": actor_address,
                        "intent_hash": intent_hash,
                        "nonce_hash": nonce_hash,
                    },
                    contract_receipt=confirmation.receipt_id,
                )
                existing = self._repository.find_idempotent(command)
                if existing is not None:
                    return existing
            self._require_version(projection, expected_version)
            self._require_unused_nonce(projection, nonce_hash)
            try:
                confirmation = self._contract.fund_credits(
                    intent_hash=intent_hash,
                    nonce_hash=nonce_hash,
                    actor_address=actor_address,
                    amount_minor_units=amount_minor_units,
                )
            except RuntimeError as exc:
                raise GroupRejected(str(exc)) from exc
            return self._repository.append(
                self._group_command(
                    group_id=group_id,
                    actor_address=actor_address,
                    idempotency_key=idempotency_key,
                    expected_version=expected_version,
                    command_type="groups.fund-credits",
                    event_type="group.credits-funded",
                    payload={
                        **parameters,
                        "actor_address": actor_address,
                        "intent_hash": intent_hash,
                        "nonce_hash": nonce_hash,
                    },
                    contract_receipt=confirmation.receipt_id,
                )
            )

    def settle_obligation(
        self,
        *,
        actor_address: str,
        idempotency_key: str,
        expected_version: int,
        group_id: str,
        obligation_id: str,
        amount_minor_units: int,
        intent: SignedIntent,
        origin: str,
    ) -> AppendResult:
        group_id = _identifier("group_id", group_id)
        obligation_id = _identifier("obligation_id", obligation_id)
        actor_address = _address(actor_address)
        amount_minor_units = _money(amount_minor_units)
        parameters: dict[str, object] = {
            "group_id": group_id,
            "obligation_id": obligation_id,
            "amount_minor_units": amount_minor_units,
            "expected_version": expected_version,
        }
        intent_hash, nonce_hash = self._verify_intent(
            intent,
            actor_address=actor_address,
            resource_id=obligation_id,
            action="settlement.authorize",
            parameters=parameters,
            origin=origin,
        )
        with self._lock:
            projection = self._require_group(group_id)
            obligation = self._require_obligation(projection, obligation_id)
            source_event_id = projection.expenses[
                obligation.expense_id
            ].source_event_id
            request_command = self._group_command(
                group_id=group_id,
                actor_address=actor_address,
                idempotency_key=idempotency_key,
                expected_version=expected_version,
                command_type="groups.request-settlement",
                event_type="group.settlement-requested",
                payload={
                    **parameters,
                    "operation_id": intent_hash,
                    "debtor_address": actor_address,
                    "intent_hash": intent_hash,
                    "nonce_hash": nonce_hash,
                },
                source_references=(source_event_id,),
            )
            existing_request = self._repository.find_idempotent(request_command)
            if existing_request is not None:
                confirmation = self._contract.receipt(intent_hash)
                if confirmation is None:
                    try:
                        confirmation = self._contract.settle_obligation(
                            intent_hash=intent_hash,
                            nonce_hash=nonce_hash,
                            obligation_id=obligation_id,
                            actor_address=actor_address,
                            amount_minor_units=amount_minor_units,
                        )
                    except RuntimeError as exc:
                        raise GroupRejected(str(exc)) from exc
                return self._finalize_settlement(
                    group_id=group_id,
                    actor_address=actor_address,
                    request_event_id=existing_request.event.event_id,
                    confirmation=confirmation,
                )
            self._require_version(projection, expected_version)
            if obligation.debtor_address != actor_address:
                raise GroupRejected("only the debtor may settle this obligation")
            if obligation.status not in {
                ObligationStatus.OPEN,
                ObligationStatus.PARTIALLY_SETTLED,
            }:
                raise GroupRejected("obligation is not open for settlement")
            if amount_minor_units > obligation.outstanding_minor_units:
                raise GroupRejected("settlement exceeds the outstanding obligation")
            if self._contract.credit_balance(actor_address) < amount_minor_units:
                raise GroupRejected("insufficient non-redeemable credits")
            self._require_unused_nonce(projection, nonce_hash)
            request = self._repository.append(request_command)
            try:
                confirmation = self._contract.settle_obligation(
                    intent_hash=intent_hash,
                    nonce_hash=nonce_hash,
                    obligation_id=obligation_id,
                    actor_address=actor_address,
                    amount_minor_units=amount_minor_units,
                )
            except RuntimeError as exc:
                raise GroupRejected(str(exc)) from exc
            if self._after_contract is not None:
                self._after_contract(intent_hash)
            return self._finalize_settlement(
                group_id=group_id,
                actor_address=actor_address,
                request_event_id=request.event.event_id,
                confirmation=confirmation,
            )

    def reconcile_group(self, group_id: str) -> tuple[AppendResult, ...]:
        group_id = _identifier("group_id", group_id)
        repaired: list[AppendResult] = []
        with self._lock:
            projection = self._require_group(group_id)
            for request in projection.settlement_requests.values():
                if request.confirmed:
                    continue
                confirmation = self._contract.receipt(request.intent_hash)
                if confirmation is None or confirmation.operation != "settle":
                    continue
                repaired.append(
                    self._finalize_settlement(
                        group_id=group_id,
                        actor_address=request.debtor_address,
                        request_event_id=request.source_event_id,
                        confirmation=confirmation,
                    )
                )
            projection = self._require_group(group_id)
            for obligation in projection.obligations.values():
                if obligation.status in {
                    ObligationStatus.OPEN,
                    ObligationStatus.PARTIALLY_SETTLED,
                    ObligationStatus.SETTLED,
                }:
                    self._propagate_open_obligation(group_id, obligation)
            cumulative_by_obligation: dict[str, int] = {}
            for request in projection.settlement_requests.values():
                if request.confirmed and request.contract_receipt is not None:
                    if request.confirmation_source_event_id is None:
                        raise GroupRejected(
                            "settlement confirmation is missing event provenance"
                        )
                    obligation = self._require_obligation(
                        projection, request.obligation_id
                    )
                    cumulative = (
                        cumulative_by_obligation.get(request.obligation_id, 0)
                        + request.amount_minor_units
                    )
                    cumulative_by_obligation[request.obligation_id] = cumulative
                    self._propagate_settlement(
                        group_id,
                        obligation,
                        request.amount_minor_units,
                        request.contract_receipt,
                        request.confirmation_source_event_id,
                        cumulative,
                    )
        return tuple(repaired)

    def overview(self, *, actor_address: str, group_id: str) -> GroupProjection:
        group_id = _identifier("group_id", group_id)
        actor_address = _address(actor_address)
        projection = self._require_group(group_id)
        self._require_member(projection, actor_address)
        return projection

    def list_groups(self, *, actor_address: str) -> tuple[GroupProjection, ...]:
        actor_address = _address(actor_address)
        directory = self._directory(actor_address)
        groups: list[GroupProjection] = []
        for group_id in directory.group_ids:
            projection = self._projection(group_id)
            member = projection.members.get(actor_address)
            if projection.group_id is not None and member is not None and member.active:
                groups.append(projection)
        return tuple(groups)

    def _finalize_settlement(
        self,
        *,
        group_id: str,
        actor_address: str,
        request_event_id: str,
        confirmation: ContractConfirmation,
    ) -> AppendResult:
        if confirmation.operation != "settle":
            raise GroupRejected("contract receipt is not a settlement")
        projection = self._require_group(group_id)
        request = projection.settlement_requests.get(confirmation.intent_hash)
        if request is None:
            raise GroupRejected("settlement request is missing")
        if request.source_event_id != request_event_id:
            raise GroupRejected("settlement request provenance mismatch")
        obligation = self._require_obligation(projection, request.obligation_id)
        try:
            contract_obligation = self._contract.obligation(request.obligation_id)
            debtor_balance = self._contract.credit_balance(
                contract_obligation.debtor_address
            )
            creditor_balance = self._contract.credit_balance(
                contract_obligation.creditor_address
            )
        except RuntimeError as exc:
            raise GroupRejected(str(exc)) from exc
        expected_contract_settled = obligation.settled_minor_units + (
            0 if request.confirmed else request.amount_minor_units
        )
        if (
            contract_obligation.creditor_address != obligation.creditor_address
            or contract_obligation.debtor_address != obligation.debtor_address
            or contract_obligation.amount_minor_units != obligation.amount_minor_units
            or contract_obligation.settled_minor_units < expected_contract_settled
        ):
            raise GroupRejected("contract obligation does not match the settlement")
        confirmation = replace(
            confirmation,
            debtor_credit_balance=debtor_balance,
            creditor_credit_balance=creditor_balance,
        )
        if request.confirmed:
            if request.confirmation_source_event_id is None:
                raise GroupRejected("settlement confirmation provenance is missing")
            confirmation_version = (
                projection.source_event_ids.index(
                    request.confirmation_source_event_id
                )
                + 1
            )
            command = self._settlement_confirmation_command(
                group_id,
                actor_address,
                projection,
                request,
                confirmation,
                expected_version=confirmation_version - 1,
            )
            existing = self._repository.find_idempotent(command)
            if existing is None:
                raise GroupRejected("settlement confirmation is inconsistent")
            return existing
        if confirmation.amount_minor_units != request.amount_minor_units:
            raise GroupRejected("contract settlement amount mismatch")
        command = self._settlement_confirmation_command(
            group_id, actor_address, projection, request, confirmation
        )
        result = self._repository.append(command)
        updated = self._require_group(group_id)
        obligation = self._require_obligation(updated, request.obligation_id)
        self._propagate_settlement(
            group_id,
            obligation,
            request.amount_minor_units,
            confirmation.receipt_id,
            result.event.event_id,
            obligation.settled_minor_units,
        )
        return result

    def _settlement_confirmation_command(
        self,
        group_id: str,
        actor_address: str,
        projection: GroupProjection,
        request: object,
        confirmation: ContractConfirmation,
        *,
        expected_version: int | None = None,
    ) -> AppendEventCommand:
        from server.app.domain.groups import SettlementRequest

        if not isinstance(request, SettlementRequest):
            raise GroupRejected("invalid settlement request")
        return self._group_command(
            group_id=group_id,
            actor_address=actor_address,
            idempotency_key=f"confirm-{confirmation.intent_hash[:96]}",
            expected_version=(
                projection.projection_version
                if expected_version is None
                else expected_version
            ),
            command_type="groups.confirm-settlement",
            event_type="group.settlement-confirmed",
            payload={
                "operation_id": request.operation_id,
                "obligation_id": request.obligation_id,
                "amount_minor_units": confirmation.amount_minor_units,
                "debtor_credit_balance": confirmation.debtor_credit_balance,
                "creditor_credit_balance": confirmation.creditor_credit_balance,
                "intent_hash": confirmation.intent_hash,
            },
            source_references=(request.source_event_id,),
            contract_receipt=confirmation.receipt_id,
        )

    def _propagate_open_obligation(
        self, group_id: str, obligation: GroupObligation
    ) -> None:
        if self._finance is None:
            return
        if (
            obligation.opened_source_event_id is None
            or obligation.approval_receipt is None
        ):
            raise GroupRejected("open obligation is missing contract provenance")
        due_on = obligation.due_on
        for address, direction in (
            (obligation.debtor_address, ObligationDirection.PAYABLE),
            (obligation.creditor_address, ObligationDirection.RECEIVABLE),
        ):
            overview = self._finance.overview(
                actor_address=address, month=self._clock().strftime("%Y-%m")
            )
            existing_obligation = overview.projection.obligations.get(
                obligation.obligation_id
            )
            if existing_obligation is not None:
                if (
                    existing_obligation.direction != direction
                    or existing_obligation.amount_minor_units
                    != obligation.amount_minor_units
                ):
                    raise GroupRejected("Finance obligation does not match contract")
                continue
            try:
                self._finance.record_confirmed_obligation(
                    actor_address=address,
                    idempotency_key=_derived_id(
                        "grp-open", group_id, obligation.obligation_id, direction.value
                    ),
                    expected_version=overview.projection.projection_version,
                    obligation_id=obligation.obligation_id,
                    direction=direction,
                    amount_minor_units=obligation.amount_minor_units,
                    due_on=due_on,
                    source_event_id=obligation.opened_source_event_id,
                    contract_receipt=obligation.approval_receipt,
                )
            except ValueError as exc:
                if "already exists" not in str(exc):
                    raise

    def _propagate_settlement(
        self,
        group_id: str,
        obligation: GroupObligation,
        amount_minor_units: int,
        receipt_id: str,
        source_event_id: str,
        expected_cumulative_minor_units: int,
    ) -> None:
        if self._finance is None:
            return
        for address in (obligation.debtor_address, obligation.creditor_address):
            overview = self._finance.overview(
                actor_address=address, month=self._clock().strftime("%Y-%m")
            )
            finance_obligation = overview.projection.obligations.get(
                obligation.obligation_id
            )
            if finance_obligation is None:
                raise GroupRejected("Finance obligation is missing")
            if (
                finance_obligation.settled_minor_units
                >= expected_cumulative_minor_units
            ):
                continue
            if (
                finance_obligation.settled_minor_units + amount_minor_units
                != expected_cumulative_minor_units
            ):
                raise GroupRejected("Finance settlement projection is inconsistent")
            self._finance.record_confirmed_obligation_settlement(
                actor_address=address,
                idempotency_key=_derived_id(
                    "grp-settle", group_id, receipt_id, address
                ),
                expected_version=overview.projection.projection_version,
                obligation_id=obligation.obligation_id,
                amount_minor_units=amount_minor_units,
                source_event_id=source_event_id,
                contract_receipt=receipt_id,
            )

    def _verify_intent(
        self,
        intent: SignedIntent,
        *,
        actor_address: str,
        resource_id: str,
        action: str,
        parameters: Mapping[str, object],
        origin: str,
    ) -> tuple[str, str]:
        if origin not in self._allowed_origins:
            raise GroupRejected("origin is not allowed")
        if intent.actor_address != actor_address:
            raise GroupRejected("signed actor does not match the session")
        if intent.resource_id != resource_id:
            raise GroupRejected("signed intent resource mismatch")
        try:
            intent_hash = verify_signed_intent(
                intent,
                parameters=parameters,
                origin=origin,
                now=self._clock(),
                policy=IntentPolicy(action=action),
            )
        except IntentRejected as exc:
            raise GroupRejected(str(exc)) from exc
        return intent_hash, hashlib.sha256(intent.nonce.encode()).hexdigest()

    def _projection(self, group_id: str) -> GroupProjection:
        events = self._repository.load_stream(
            tenant_id=_group_tenant(group_id),
            aggregate_type="group",
            aggregate_id=group_id,
        )
        return rebuild_projection(
            events, initial=GroupProjection(), reducer=reduce_group_event
        )

    def _directory(self, actor_address: str) -> GroupDirectory:
        tenant, aggregate, _ = _actor_identity(actor_address)
        events = self._repository.load_stream(
            tenant_id=tenant,
            aggregate_type="group-directory",
            aggregate_id=aggregate,
        )
        return rebuild_projection(
            events, initial=GroupDirectory(), reducer=reduce_group_directory
        )

    def _link_directory(self, actor_address: str, group_id: str) -> None:
        directory = self._directory(actor_address)
        if group_id in directory.group_ids:
            return
        tenant, aggregate, actor_id = _actor_identity(actor_address)
        command = AppendEventCommand(
            tenant_id=tenant,
            actor_id=actor_id,
            command_type="groups.link-directory",
            idempotency_key=_derived_id("dir", actor_address, group_id),
            event_type="group.directory-linked",
            aggregate_type="group-directory",
            aggregate_id=aggregate,
            expected_version=directory.projection_version,
            payload={"group_id": group_id},
        )
        self._repository.append(command)

    def _require_group(self, group_id: str) -> GroupProjection:
        projection = self._projection(group_id)
        if projection.group_id is None:
            raise GroupRejected("group does not exist")
        return projection

    @staticmethod
    def _require_member(projection: GroupProjection, actor_address: str) -> None:
        member = projection.members.get(actor_address)
        if member is None or not member.active:
            raise GroupRejected("wallet is not an active group member")

    @staticmethod
    def _require_owner(projection: GroupProjection, actor_address: str) -> None:
        if projection.owner_address != actor_address:
            raise GroupRejected("only the group owner may perform this action")

    @staticmethod
    def _require_version(projection: GroupProjection, expected_version: int) -> None:
        if projection.projection_version != expected_version:
            raise GroupRejected(
                f"expected group version {expected_version}, "
                f"found {projection.projection_version}"
            )

    @staticmethod
    def _require_obligation(
        projection: GroupProjection, obligation_id: str
    ) -> GroupObligation:
        obligation = projection.obligations.get(obligation_id)
        if obligation is None:
            raise GroupRejected("obligation does not exist")
        return obligation

    @staticmethod
    def _require_unused_nonce(projection: GroupProjection, nonce_hash: str) -> None:
        if nonce_hash in projection.used_nonce_hashes:
            raise GroupRejected("intent nonce was already used")

    @staticmethod
    def _group_command(
        *,
        group_id: str,
        actor_address: str,
        idempotency_key: str,
        expected_version: int,
        command_type: str,
        event_type: str,
        payload: dict[str, object],
        source_references: tuple[str, ...] = (),
        contract_receipt: str | None = None,
    ) -> AppendEventCommand:
        return AppendEventCommand(
            tenant_id=_group_tenant(group_id),
            actor_id=_actor_id(actor_address),
            command_type=command_type,
            idempotency_key=_identifier("idempotency_key", idempotency_key),
            event_type=event_type,
            aggregate_type="group",
            aggregate_id=group_id,
            expected_version=expected_version,
            payload=payload,
            source_references=source_references,
            contract_receipt=contract_receipt,
        )


def _group_tenant(group_id: str) -> str:
    return "group-" + hashlib.sha256(group_id.encode()).hexdigest()[:32]


def _actor_identity(actor_address: str) -> tuple[str, str, str]:
    digest = hashlib.sha256(actor_address.encode()).hexdigest()[:32]
    return f"tenant-{digest}", f"groups-{digest}", f"wallet-{digest}"


def _actor_id(actor_address: str) -> str:
    return _actor_identity(actor_address)[2]


def _identifier(name: str, value: str) -> str:
    if not _ID.fullmatch(value):
        raise GroupRejected(f"{name} must be an opaque identifier")
    return value


def _address(value: str) -> str:
    normalized = value.lower()
    if not _ADDRESS.fullmatch(normalized):
        raise GroupRejected("wallet address must be a 20-byte hexadecimal address")
    return normalized


def _label(name: str, value: str, maximum: int) -> str:
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > maximum:
        raise GroupRejected(f"{name} must contain 1 to {maximum} characters")
    return normalized


def _money(value: int) -> int:
    if isinstance(value, bool) or value <= 0 or value > _MAX_MONEY:
        raise GroupRejected("money must be positive integer USD cents")
    return value


def _derived_id(prefix: str, *values: str) -> str:
    digest = hashlib.sha256("|".join(values).encode()).hexdigest()[:32]
    return f"{prefix}-{digest}"
