from __future__ import annotations

import hashlib
import re
import threading
from dataclasses import dataclass
from datetime import UTC, date, datetime

from server.app.application.projections import rebuild_projection
from server.app.domain.events import AppendEventCommand, AppendResult
from server.app.domain.finance import (
    EntryDirection,
    FinanceProjection,
    MonthlyFinanceSummary,
    ObligationDirection,
    reduce_finance_event,
    summarize_month,
)
from server.app.infrastructure.event_repository import EncryptedEventRepository

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MONTH = re.compile(r"^\d{4}-\d{2}$")
_MAX_MONEY = 9_000_000_000_000_000


class FinanceRejected(ValueError):
    pass


@dataclass(frozen=True)
class FinanceOverview:
    projection: FinanceProjection
    summary: MonthlyFinanceSummary


class FinanceService:
    def __init__(self, repository: EncryptedEventRepository) -> None:
        self._repository = repository
        self._lock = threading.Lock()

    def create_category(
        self,
        *,
        actor_address: str,
        idempotency_key: str,
        expected_version: int,
        category_id: str,
        name: str,
        direction: EntryDirection,
    ) -> AppendResult:
        category_id = _identifier("category_id", category_id)
        name = _label("name", name, maximum=80)
        command = self._command(
            actor_address=actor_address,
            idempotency_key=idempotency_key,
            expected_version=expected_version,
            command_type="finance.create-category",
            event_type="finance.category-created",
            payload={
                "category_id": category_id,
                "name": name,
                "direction": direction.value,
            },
        )
        with self._lock:
            if (existing := self._repository.find_idempotent(command)) is not None:
                return existing
            projection = self._projection(actor_address)
            if category_id in projection.categories:
                raise FinanceRejected("category ID already exists")
            return self._repository.append(command)

    def record_transaction(
        self,
        *,
        actor_address: str,
        idempotency_key: str,
        expected_version: int,
        transaction_id: str,
        direction: EntryDirection,
        category_id: str,
        amount_minor_units: int,
        occurred_on: date,
        description: str,
        recurring_entry_id: str | None,
    ) -> AppendResult:
        transaction_id = _identifier("transaction_id", transaction_id)
        category_id = _identifier("category_id", category_id)
        amount_minor_units = _money(amount_minor_units)
        description = _label("description", description, maximum=160)
        if recurring_entry_id is not None:
            recurring_entry_id = _identifier(
                "recurring_entry_id", recurring_entry_id
            )
        command = self._command(
            actor_address=actor_address,
            idempotency_key=idempotency_key,
            expected_version=expected_version,
            command_type="finance.record-transaction",
            event_type="finance.transaction-recorded",
            payload={
                "transaction_id": transaction_id,
                "direction": direction.value,
                "category_id": category_id,
                "amount_minor_units": amount_minor_units,
                "currency": "USD",
                "occurred_on": occurred_on.isoformat(),
                "description": description,
                "recurring_entry_id": recurring_entry_id,
            },
        )
        with self._lock:
            if (existing := self._repository.find_idempotent(command)) is not None:
                return existing
            projection = self._projection(actor_address)
            if transaction_id in projection.transactions:
                raise FinanceRejected("transaction ID already exists")
            category = projection.categories.get(category_id)
            if category is None or not category.active:
                raise FinanceRejected("category is not active")
            if category.direction != direction:
                raise FinanceRejected("transaction direction does not match category")
            if recurring_entry_id is not None:
                recurring = projection.recurring_entries.get(recurring_entry_id)
                if recurring is None or not recurring.active:
                    raise FinanceRejected("recurring entry is not active")
                if recurring.direction != direction or recurring.category_id != category_id:
                    raise FinanceRejected(
                        "transaction does not match the recurring entry"
                    )
            return self._repository.append(command)

    def void_transaction(
        self,
        *,
        actor_address: str,
        idempotency_key: str,
        expected_version: int,
        transaction_id: str,
        reason: str,
    ) -> AppendResult:
        transaction_id = _identifier("transaction_id", transaction_id)
        reason = _label("reason", reason, maximum=160)
        with self._lock:
            projection = self._projection(actor_address)
            transaction = projection.transactions.get(transaction_id)
            if transaction is None:
                raise FinanceRejected("transaction cannot be voided")
            command = self._command(
                actor_address=actor_address,
                idempotency_key=idempotency_key,
                expected_version=expected_version,
                command_type="finance.void-transaction",
                event_type="finance.transaction-voided",
                payload={"transaction_id": transaction_id, "reason": reason},
                source_references=(transaction.source_event_id,),
            )
            if (existing := self._repository.find_idempotent(command)) is not None:
                return existing
            if transaction.voided:
                raise FinanceRejected("transaction cannot be voided")
            return self._repository.append(command)

    def set_budget(
        self,
        *,
        actor_address: str,
        idempotency_key: str,
        expected_version: int,
        budget_id: str,
        category_id: str,
        month: str,
        limit_minor_units: int,
    ) -> AppendResult:
        budget_id = _identifier("budget_id", budget_id)
        category_id = _identifier("category_id", category_id)
        month = _month(month)
        limit_minor_units = _money(limit_minor_units)
        command = self._command(
            actor_address=actor_address,
            idempotency_key=idempotency_key,
            expected_version=expected_version,
            command_type="finance.set-budget",
            event_type="finance.budget-set",
            payload={
                "budget_id": budget_id,
                "category_id": category_id,
                "month": month,
                "limit_minor_units": limit_minor_units,
                "currency": "USD",
            },
        )
        with self._lock:
            if (existing := self._repository.find_idempotent(command)) is not None:
                return existing
            projection = self._projection(actor_address)
            category = projection.categories.get(category_id)
            if (
                category is None
                or not category.active
                or category.direction != EntryDirection.EXPENSE
            ):
                raise FinanceRejected("budget category must be an active expense")
            conflicting = next(
                (
                    budget
                    for budget in projection.budgets.values()
                    if budget.category_id == category_id
                    and budget.month == month
                    and budget.budget_id != budget_id
                ),
                None,
            )
            if conflicting is not None:
                raise FinanceRejected(
                    "a budget already exists for this category and month"
                )
            return self._repository.append(command)

    def create_recurring_entry(
        self,
        *,
        actor_address: str,
        idempotency_key: str,
        expected_version: int,
        recurring_entry_id: str,
        direction: EntryDirection,
        category_id: str,
        amount_minor_units: int,
        description: str,
        starts_on: date,
        ends_on: date | None,
    ) -> AppendResult:
        recurring_entry_id = _identifier("recurring_entry_id", recurring_entry_id)
        category_id = _identifier("category_id", category_id)
        amount_minor_units = _money(amount_minor_units)
        description = _label("description", description, maximum=160)
        if ends_on is not None and ends_on < starts_on:
            raise FinanceRejected("recurring end date cannot precede its start date")
        command = self._command(
            actor_address=actor_address,
            idempotency_key=idempotency_key,
            expected_version=expected_version,
            command_type="finance.create-recurring-entry",
            event_type="finance.recurring-entry-created",
            payload={
                "recurring_entry_id": recurring_entry_id,
                "direction": direction.value,
                "category_id": category_id,
                "amount_minor_units": amount_minor_units,
                "currency": "USD",
                "description": description,
                "cadence": "monthly",
                "starts_on": starts_on.isoformat(),
                "ends_on": ends_on.isoformat() if ends_on is not None else None,
            },
        )
        with self._lock:
            if (existing := self._repository.find_idempotent(command)) is not None:
                return existing
            projection = self._projection(actor_address)
            if recurring_entry_id in projection.recurring_entries:
                raise FinanceRejected("recurring entry ID already exists")
            category = projection.categories.get(category_id)
            if category is None or not category.active:
                raise FinanceRejected("category is not active")
            if category.direction != direction:
                raise FinanceRejected("recurring direction does not match category")
            return self._repository.append(command)

    def deactivate_recurring_entry(
        self,
        *,
        actor_address: str,
        idempotency_key: str,
        expected_version: int,
        recurring_entry_id: str,
    ) -> AppendResult:
        recurring_entry_id = _identifier("recurring_entry_id", recurring_entry_id)
        with self._lock:
            projection = self._projection(actor_address)
            recurring = projection.recurring_entries.get(recurring_entry_id)
            if recurring is None:
                raise FinanceRejected("recurring entry cannot be deactivated")
            command = self._command(
                actor_address=actor_address,
                idempotency_key=idempotency_key,
                expected_version=expected_version,
                command_type="finance.deactivate-recurring-entry",
                event_type="finance.recurring-entry-deactivated",
                payload={"recurring_entry_id": recurring_entry_id},
                source_references=(recurring.source_event_id,),
            )
            if (existing := self._repository.find_idempotent(command)) is not None:
                return existing
            if not recurring.active:
                raise FinanceRejected("recurring entry cannot be deactivated")
            return self._repository.append(command)

    def record_confirmed_obligation(
        self,
        *,
        actor_address: str,
        idempotency_key: str,
        expected_version: int,
        obligation_id: str,
        direction: ObligationDirection,
        amount_minor_units: int,
        due_on: date | None,
        source_event_id: str,
        contract_receipt: str,
    ) -> AppendResult:
        """Application-only gateway used after confirmed ResContract state."""
        obligation_id = _identifier("obligation_id", obligation_id)
        source_event_id = _identifier("source_event_id", source_event_id)
        contract_receipt = _identifier("contract_receipt", contract_receipt)
        amount_minor_units = _money(amount_minor_units)
        command = self._command(
            actor_address=actor_address,
            idempotency_key=idempotency_key,
            expected_version=expected_version,
            command_type="finance.record-confirmed-obligation",
            event_type="finance.obligation-opened",
            payload={
                "obligation_id": obligation_id,
                "direction": direction.value,
                "amount_minor_units": amount_minor_units,
                "currency": "USD",
                "due_on": due_on.isoformat() if due_on is not None else None,
            },
            source_references=(source_event_id,),
            contract_receipt=contract_receipt,
        )
        with self._lock:
            if (existing := self._repository.find_idempotent(command)) is not None:
                return existing
            projection = self._projection(actor_address)
            if obligation_id in projection.obligations:
                raise FinanceRejected("obligation ID already exists")
            return self._repository.append(command)

    def overview(self, *, actor_address: str, month: str) -> FinanceOverview:
        month = _month(month)
        projection = self._projection(actor_address)
        return FinanceOverview(
            projection=projection,
            summary=summarize_month(projection, month=month),
        )

    def _projection(self, actor_address: str) -> FinanceProjection:
        tenant_id, aggregate_id, _ = _identity(actor_address)
        events = self._repository.load_stream(
            tenant_id=tenant_id,
            aggregate_type="finance-account",
            aggregate_id=aggregate_id,
        )
        return rebuild_projection(
            events,
            initial=FinanceProjection(),
            reducer=reduce_finance_event,
        )

    def _command(
        self,
        *,
        actor_address: str,
        idempotency_key: str,
        expected_version: int,
        command_type: str,
        event_type: str,
        payload: dict[str, object],
        source_references: tuple[str, ...] = (),
        contract_receipt: str | None = None,
    ) -> AppendEventCommand:
        tenant_id, aggregate_id, actor_id = _identity(actor_address)
        return AppendEventCommand(
            tenant_id=tenant_id,
            actor_id=actor_id,
            command_type=command_type,
            idempotency_key=_identifier("idempotency_key", idempotency_key),
            event_type=event_type,
            aggregate_type="finance-account",
            aggregate_id=aggregate_id,
            expected_version=expected_version,
            payload=payload,
            source_references=source_references,
            contract_receipt=contract_receipt,
        )


def _identity(actor_address: str) -> tuple[str, str, str]:
    digest = hashlib.sha256(actor_address.encode("utf-8")).hexdigest()[:32]
    return f"tenant-{digest}", f"finance-{digest}", f"wallet-{digest}"


def _identifier(name: str, value: str) -> str:
    if not _ID.fullmatch(value):
        raise FinanceRejected(f"{name} must be an opaque identifier")
    return value


def _label(name: str, value: str, *, maximum: int) -> str:
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > maximum:
        raise FinanceRejected(f"{name} must be between 1 and {maximum} characters")
    return normalized


def _money(value: int) -> int:
    if isinstance(value, bool) or value <= 0 or value > _MAX_MONEY:
        raise FinanceRejected("money must be positive integer USD cents")
    return value


def _month(value: str) -> str:
    if not _MONTH.fullmatch(value):
        raise FinanceRejected("month must use YYYY-MM")
    try:
        datetime.strptime(value, "%Y-%m").replace(tzinfo=UTC)
    except ValueError as exc:
        raise FinanceRejected("month must use YYYY-MM") from exc
    return value
