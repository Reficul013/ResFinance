from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from enum import StrEnum

from server.app.domain.events import DomainEvent


class GroupProjectionError(ValueError):
    pass


class ObligationStatus(StrEnum):
    PENDING = "pending"
    OPEN = "open"
    PARTIALLY_SETTLED = "partially_settled"
    SETTLED = "settled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ContractConfirmation:
    receipt_id: str
    intent_hash: str
    operation: str
    amount_minor_units: int
    obligation_status: ObligationStatus | None = None
    debtor_credit_balance: int | None = None
    creditor_credit_balance: int | None = None


@dataclass(frozen=True)
class ContractObligationState:
    obligation_id: str
    creditor_address: str
    debtor_address: str
    amount_minor_units: int
    settled_minor_units: int
    status: ObligationStatus


@dataclass(frozen=True)
class GroupMember:
    actor_address: str
    display_name: str
    active: bool
    source_event_id: str


@dataclass(frozen=True)
class GroupExpense:
    expense_id: str
    payer_address: str
    description: str
    amount_minor_units: int
    occurred_on: date
    shares: dict[str, int]
    obligation_ids: tuple[str, ...]
    source_event_id: str
    contract_receipts: tuple[str, ...]


@dataclass(frozen=True)
class GroupObligation:
    obligation_id: str
    expense_id: str
    creditor_address: str
    debtor_address: str
    amount_minor_units: int
    settled_minor_units: int
    due_on: date | None
    status: ObligationStatus
    source_event_id: str
    contract_receipts: tuple[str, ...]
    opened_source_event_id: str | None = None
    approval_receipt: str | None = None

    @property
    def outstanding_minor_units(self) -> int:
        return self.amount_minor_units - self.settled_minor_units


@dataclass(frozen=True)
class SettlementRequest:
    operation_id: str
    obligation_id: str
    debtor_address: str
    amount_minor_units: int
    intent_hash: str
    source_event_id: str
    confirmed: bool
    contract_receipt: str | None = None
    confirmation_source_event_id: str | None = None


@dataclass(frozen=True)
class GroupNotification:
    notification_id: str
    recipient_address: str
    kind: str
    message: str
    source_event_id: str


@dataclass(frozen=True)
class GroupProjection:
    group_id: str | None = None
    name: str | None = None
    owner_address: str | None = None
    projection_version: int = 0
    as_of_utc: datetime | None = None
    members: dict[str, GroupMember] = field(default_factory=dict)
    expenses: dict[str, GroupExpense] = field(default_factory=dict)
    obligations: dict[str, GroupObligation] = field(default_factory=dict)
    settlement_requests: dict[str, SettlementRequest] = field(default_factory=dict)
    credit_balances: dict[str, int] = field(default_factory=dict)
    notifications: tuple[GroupNotification, ...] = ()
    used_nonce_hashes: tuple[str, ...] = ()
    source_event_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class GroupDirectory:
    projection_version: int = 0
    group_ids: tuple[str, ...] = ()


def reduce_group_event(
    projection: GroupProjection, event: DomainEvent
) -> GroupProjection:
    if event.aggregate_type != "group":
        raise GroupProjectionError("group reducer received another aggregate type")
    if event.aggregate_version != projection.projection_version + 1:
        raise GroupProjectionError("group event versions are not contiguous")

    members = dict(projection.members)
    expenses = dict(projection.expenses)
    obligations = dict(projection.obligations)
    requests = dict(projection.settlement_requests)
    balances = dict(projection.credit_balances)
    notifications = list(projection.notifications)
    used_nonce_hashes = projection.used_nonce_hashes
    group_id = projection.group_id
    name = projection.name
    owner = projection.owner_address
    payload = event.payload

    if event.event_type == "group.created":
        if group_id is not None:
            raise GroupProjectionError("group already exists")
        group_id = _text(payload, "group_id")
        name = _text(payload, "name")
        owner = _text(payload, "owner_address")
        members[owner] = GroupMember(
            actor_address=owner,
            display_name=_text(payload, "owner_display_name"),
            active=True,
            source_event_id=event.event_id,
        )
    elif event.event_type == "group.member-added":
        address = _text(payload, "actor_address")
        if address in members:
            raise GroupProjectionError("group member already exists")
        members[address] = GroupMember(
            actor_address=address,
            display_name=_text(payload, "display_name"),
            active=True,
            source_event_id=event.event_id,
        )
    elif event.event_type == "group.expense-created":
        expense_id = _text(payload, "expense_id")
        if expense_id in expenses:
            raise GroupProjectionError("group expense already exists")
        shares = _money_map(payload, "shares")
        obligation_values = payload.get("obligations")
        if not isinstance(obligation_values, list):
            raise GroupProjectionError("obligations must be a list")
        obligation_ids: list[str] = []
        receipts = _text_tuple(payload, "contract_receipts")
        for value in obligation_values:
            if not isinstance(value, dict):
                raise GroupProjectionError("obligation must be an object")
            obligation_id = _text(value, "obligation_id")
            if obligation_id in obligations:
                raise GroupProjectionError("group obligation already exists")
            obligation_ids.append(obligation_id)
            obligations[obligation_id] = GroupObligation(
                obligation_id=obligation_id,
                expense_id=expense_id,
                creditor_address=_text(value, "creditor_address"),
                debtor_address=_text(value, "debtor_address"),
                amount_minor_units=_positive_int(value, "amount_minor_units"),
                settled_minor_units=0,
                due_on=_optional_date(value.get("due_on")),
                status=ObligationStatus.PENDING,
                source_event_id=event.event_id,
                contract_receipts=receipts,
            )
            notifications.append(
                GroupNotification(
                    notification_id=f"notice-{obligation_id}-pending",
                    recipient_address=_text(value, "debtor_address"),
                    kind="approval_required",
                    message="A shared-expense obligation needs your approval.",
                    source_event_id=event.event_id,
                )
            )
        expenses[expense_id] = GroupExpense(
            expense_id=expense_id,
            payer_address=_text(payload, "payer_address"),
            description=_text(payload, "description"),
            amount_minor_units=_positive_int(payload, "amount_minor_units"),
            occurred_on=_date(payload, "occurred_on"),
            shares=shares,
            obligation_ids=tuple(obligation_ids),
            source_event_id=event.event_id,
            contract_receipts=receipts,
        )
    elif event.event_type in {
        "group.obligation-approved",
        "group.obligation-rejected",
        "group.obligation-cancelled",
    }:
        obligation_id = _text(payload, "obligation_id")
        obligation = _obligation(obligations, obligation_id)
        status = {
            "group.obligation-approved": ObligationStatus.OPEN,
            "group.obligation-rejected": ObligationStatus.REJECTED,
            "group.obligation-cancelled": ObligationStatus.CANCELLED,
        }[event.event_type]
        if obligation.status != ObligationStatus.PENDING:
            raise GroupProjectionError("pending obligation required")
        receipt = _receipt(event)
        obligations[obligation_id] = replace(
            obligation,
            status=status,
            source_event_id=event.event_id,
            contract_receipts=(*obligation.contract_receipts, receipt),
            opened_source_event_id=(
                event.event_id
                if status == ObligationStatus.OPEN
                else obligation.opened_source_event_id
            ),
            approval_receipt=(
                receipt
                if status == ObligationStatus.OPEN
                else obligation.approval_receipt
            ),
        )
        notifications.append(
            GroupNotification(
                notification_id=f"notice-{event.event_id}",
                recipient_address=obligation.creditor_address,
                kind=f"obligation_{status.value}",
                message=f"An obligation is now {status.value.replace('_', ' ')}.",
                source_event_id=event.event_id,
            )
        )
    elif event.event_type == "group.credits-funded":
        address = _text(payload, "actor_address")
        amount = _positive_int(payload, "amount_minor_units")
        balances[address] = balances.get(address, 0) + amount
    elif event.event_type == "group.settlement-requested":
        operation_id = _text(payload, "operation_id")
        if operation_id in requests:
            raise GroupProjectionError("settlement request already exists")
        requests[operation_id] = SettlementRequest(
            operation_id=operation_id,
            obligation_id=_text(payload, "obligation_id"),
            debtor_address=_text(payload, "debtor_address"),
            amount_minor_units=_positive_int(payload, "amount_minor_units"),
            intent_hash=_text(payload, "intent_hash"),
            source_event_id=event.event_id,
            confirmed=False,
        )
    elif event.event_type == "group.settlement-confirmed":
        operation_id = _text(payload, "operation_id")
        request = requests.get(operation_id)
        if request is None or request.confirmed:
            raise GroupProjectionError("pending settlement request required")
        obligation = _obligation(obligations, request.obligation_id)
        amount = _positive_int(payload, "amount_minor_units")
        settled = obligation.settled_minor_units + amount
        if settled > obligation.amount_minor_units:
            raise GroupProjectionError("settlement exceeds obligation")
        status = (
            ObligationStatus.SETTLED
            if settled == obligation.amount_minor_units
            else ObligationStatus.PARTIALLY_SETTLED
        )
        receipt = _receipt(event)
        obligations[obligation.obligation_id] = replace(
            obligation,
            settled_minor_units=settled,
            status=status,
            source_event_id=event.event_id,
            contract_receipts=(*obligation.contract_receipts, receipt),
        )
        requests[operation_id] = replace(
            request,
            confirmed=True,
            contract_receipt=receipt,
            confirmation_source_event_id=event.event_id,
        )
        balances[obligation.debtor_address] = _nonnegative_int(
            payload, "debtor_credit_balance"
        )
        balances[obligation.creditor_address] = _nonnegative_int(
            payload, "creditor_credit_balance"
        )
        notifications.append(
            GroupNotification(
                notification_id=f"notice-{event.event_id}",
                recipient_address=obligation.creditor_address,
                kind="settlement_confirmed",
                message="A non-redeemable credit settlement was confirmed.",
                source_event_id=event.event_id,
            )
        )
    else:
        raise GroupProjectionError(f"unsupported group event: {event.event_type}")

    nonce_hash = payload.get("nonce_hash")
    if nonce_hash is not None:
        if not isinstance(nonce_hash, str) or not nonce_hash:
            raise GroupProjectionError("nonce hash must be text")
        if nonce_hash in used_nonce_hashes:
            raise GroupProjectionError("intent nonce was already used")
        used_nonce_hashes = (*used_nonce_hashes, nonce_hash)

    return GroupProjection(
        group_id=group_id,
        name=name,
        owner_address=owner,
        projection_version=event.aggregate_version,
        as_of_utc=event.occurred_at_utc.astimezone(UTC),
        members=members,
        expenses=expenses,
        obligations=obligations,
        settlement_requests=requests,
        credit_balances=balances,
        notifications=tuple(notifications),
        used_nonce_hashes=used_nonce_hashes,
        source_event_ids=(*projection.source_event_ids, event.event_id),
    )


def reduce_group_directory(
    projection: GroupDirectory, event: DomainEvent
) -> GroupDirectory:
    if event.aggregate_type != "group-directory":
        raise GroupProjectionError("directory reducer received another aggregate type")
    if event.aggregate_version != projection.projection_version + 1:
        raise GroupProjectionError("directory event versions are not contiguous")
    if event.event_type != "group.directory-linked":
        raise GroupProjectionError("unsupported directory event")
    group_id = _text(event.payload, "group_id")
    group_ids = projection.group_ids
    if group_id not in group_ids:
        group_ids = (*group_ids, group_id)
    return GroupDirectory(event.aggregate_version, group_ids)


def _obligation(
    obligations: dict[str, GroupObligation], obligation_id: str
) -> GroupObligation:
    value = obligations.get(obligation_id)
    if value is None:
        raise GroupProjectionError("obligation does not exist")
    return value


def _receipt(event: DomainEvent) -> str:
    if event.contract_receipt is None:
        raise GroupProjectionError("confirmed contract event requires a receipt")
    return event.contract_receipt


def _text(value: dict[str, object], field_name: str) -> str:
    field = value.get(field_name)
    if not isinstance(field, str) or not field:
        raise GroupProjectionError(f"{field_name} must be text")
    return field


def _positive_int(value: dict[str, object], field_name: str) -> int:
    field = value.get(field_name)
    if not isinstance(field, int) or isinstance(field, bool) or field <= 0:
        raise GroupProjectionError(f"{field_name} must be positive")
    return field


def _nonnegative_int(value: dict[str, object], field_name: str) -> int:
    field = value.get(field_name)
    if not isinstance(field, int) or isinstance(field, bool) or field < 0:
        raise GroupProjectionError(f"{field_name} must be nonnegative")
    return field


def _date(value: dict[str, object], field_name: str) -> date:
    return _optional_date(_text(value, field_name)) or date.min


def _optional_date(value: object) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise GroupProjectionError("date must be ISO text")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise GroupProjectionError("date must be ISO text") from exc


def _text_tuple(value: dict[str, object], field_name: str) -> tuple[str, ...]:
    field = value.get(field_name)
    if not isinstance(field, list) or any(
        not isinstance(item, str) or not item for item in field
    ):
        raise GroupProjectionError(f"{field_name} must be text list")
    return tuple(field)


def _money_map(value: dict[str, object], field_name: str) -> dict[str, int]:
    field = value.get(field_name)
    if not isinstance(field, dict):
        raise GroupProjectionError(f"{field_name} must be an object")
    result: dict[str, int] = {}
    for key, amount in field.items():
        if (
            not isinstance(key, str)
            or not key
            or not isinstance(amount, int)
            or isinstance(amount, bool)
            or amount <= 0
        ):
            raise GroupProjectionError(f"{field_name} contains invalid money")
        result[key] = amount
    return result
