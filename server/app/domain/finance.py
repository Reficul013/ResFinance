from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Literal

from server.app.domain.events import DomainEvent

SAVINGS_FORMULA_VERSION = "finance-savings-v1"


class FinanceProjectionError(ValueError):
    pass


class EntryDirection(StrEnum):
    INCOME = "income"
    EXPENSE = "expense"


class ObligationDirection(StrEnum):
    RECEIVABLE = "receivable"
    PAYABLE = "payable"


@dataclass(frozen=True)
class Category:
    category_id: str
    name: str
    direction: EntryDirection
    active: bool
    source_event_id: str


DETERMINISTIC_CATEGORIES: tuple[Category, ...] = (
    Category(
        category_id="salary",
        name="Salary",
        direction=EntryDirection.INCOME,
        active=True,
        source_event_id="system-finance-category-v1-salary",
    ),
    Category(
        category_id="liquid-funds-transfer",
        name="Liquid Funds Transfer",
        direction=EntryDirection.INCOME,
        active=True,
        source_event_id="system-finance-category-v1-liquid-funds-transfer",
    ),
    Category(
        category_id="other-sources",
        name="Other Sources",
        direction=EntryDirection.INCOME,
        active=True,
        source_event_id="system-finance-category-v1-other-sources",
    ),
    Category(
        category_id="rent",
        name="Rent",
        direction=EntryDirection.EXPENSE,
        active=True,
        source_event_id="system-finance-category-v1-rent",
    ),
    Category(
        category_id="utilities",
        name="Utilities",
        direction=EntryDirection.EXPENSE,
        active=True,
        source_event_id="system-finance-category-v1-utilities",
    ),
    Category(
        category_id="shopping",
        name="Shopping",
        direction=EntryDirection.EXPENSE,
        active=True,
        source_event_id="system-finance-category-v1-shopping",
    ),
    Category(
        category_id="entertainment",
        name="Entertainment",
        direction=EntryDirection.EXPENSE,
        active=True,
        source_event_id="system-finance-category-v1-entertainment",
    ),
    Category(
        category_id="food-groceries",
        name="Food & Groceries",
        direction=EntryDirection.EXPENSE,
        active=True,
        source_event_id="system-finance-category-v1-food-groceries",
    ),
    Category(
        category_id="medical-bills",
        name="Medical Bills",
        direction=EntryDirection.EXPENSE,
        active=True,
        source_event_id="system-finance-category-v1-medical-bills",
    ),
    Category(
        category_id="miscellaneous",
        name="Miscellaneous",
        direction=EntryDirection.EXPENSE,
        active=True,
        source_event_id="system-finance-category-v1-miscellaneous",
    ),
)

DETERMINISTIC_CATEGORY_BY_ID = {
    category.category_id: category for category in DETERMINISTIC_CATEGORIES
}


@dataclass(frozen=True)
class Transaction:
    transaction_id: str
    direction: EntryDirection
    category_id: str
    amount_minor_units: int
    occurred_on: date
    description: str
    recurring_entry_id: str | None
    voided: bool
    source_event_id: str


@dataclass(frozen=True)
class Budget:
    budget_id: str
    category_id: str
    month: str
    limit_minor_units: int
    source_event_id: str


@dataclass(frozen=True)
class RecurringEntry:
    recurring_entry_id: str
    direction: EntryDirection
    category_id: str
    amount_minor_units: int
    description: str
    starts_on: date
    ends_on: date | None
    active: bool
    source_event_id: str


@dataclass(frozen=True)
class Obligation:
    obligation_id: str
    direction: ObligationDirection
    amount_minor_units: int
    settled_minor_units: int
    due_on: date | None
    source_event_id: str
    contract_receipt: str

    @property
    def settled(self) -> bool:
        return self.settled_minor_units == self.amount_minor_units

    @property
    def outstanding_minor_units(self) -> int:
        return self.amount_minor_units - self.settled_minor_units


@dataclass(frozen=True)
class FinanceProjection:
    projection_version: int = 0
    as_of_utc: datetime | None = None
    categories: dict[str, Category] = field(default_factory=dict)
    transactions: dict[str, Transaction] = field(default_factory=dict)
    budgets: dict[str, Budget] = field(default_factory=dict)
    recurring_entries: dict[str, RecurringEntry] = field(default_factory=dict)
    obligations: dict[str, Obligation] = field(default_factory=dict)
    source_event_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class BudgetStatus:
    budget_id: str
    category_id: str
    category_name: str
    limit_minor_units: int
    spent_minor_units: int
    remaining_minor_units: int
    utilization_basis_points: int
    status: Literal["on_track", "near_limit", "over_budget"]
    source_event_ids: tuple[str, ...]


@dataclass(frozen=True)
class MonthlyFinanceSummary:
    month: str
    income_minor_units: int
    expense_minor_units: int
    balance_minor_units: int
    receivable_minor_units: int
    payable_minor_units: int
    outstanding_recurring_income_minor_units: int
    outstanding_recurring_expense_minor_units: int
    actual_savings_minor_units: int
    projected_savings_minor_units: int
    available_savings_minor_units: int
    savings_formula_version: str
    savings_calculation_id: str
    projection_version: int
    as_of_utc: datetime | None
    source_event_ids: tuple[str, ...]
    budget_statuses: tuple[BudgetStatus, ...]


def with_deterministic_categories(
    projection: FinanceProjection,
) -> FinanceProjection:
    """Add the built-in catalog without changing event versions or provenance."""
    return replace(
        projection,
        categories={
            **projection.categories,
            **DETERMINISTIC_CATEGORY_BY_ID,
        },
    )


def reduce_finance_event(
    projection: FinanceProjection, event: DomainEvent
) -> FinanceProjection:
    if event.aggregate_type != "finance-account":
        raise FinanceProjectionError("finance reducer received another aggregate type")
    if event.aggregate_version != projection.projection_version + 1:
        raise FinanceProjectionError("finance event versions are not contiguous")

    categories = dict(projection.categories)
    transactions = dict(projection.transactions)
    budgets = dict(projection.budgets)
    recurring_entries = dict(projection.recurring_entries)
    obligations = dict(projection.obligations)
    payload = event.payload

    if event.event_type == "finance.category-created":
        category_id = _text(payload, "category_id")
        if category_id in categories:
            raise FinanceProjectionError("category already exists")
        categories[category_id] = Category(
            category_id=category_id,
            name=_text(payload, "name"),
            direction=_direction(payload),
            active=True,
            source_event_id=event.event_id,
        )
    elif event.event_type == "finance.transaction-recorded":
        transaction_id = _text(payload, "transaction_id")
        if transaction_id in transactions:
            raise FinanceProjectionError("transaction already exists")
        recurring_entry_id = payload.get("recurring_entry_id")
        if recurring_entry_id is not None and not isinstance(recurring_entry_id, str):
            raise FinanceProjectionError("recurring entry ID must be text")
        transactions[transaction_id] = Transaction(
            transaction_id=transaction_id,
            direction=_direction(payload),
            category_id=_text(payload, "category_id"),
            amount_minor_units=_positive_money(payload),
            occurred_on=_date(payload, "occurred_on"),
            description=_text(payload, "description"),
            recurring_entry_id=recurring_entry_id,
            voided=False,
            source_event_id=event.event_id,
        )
    elif event.event_type == "finance.transaction-voided":
        transaction_id = _text(payload, "transaction_id")
        transaction = transactions.get(transaction_id)
        if transaction is None or transaction.voided:
            raise FinanceProjectionError("transaction cannot be voided")
        transactions[transaction_id] = replace(transaction, voided=True)
    elif event.event_type == "finance.budget-set":
        budget_id = _text(payload, "budget_id")
        budgets[budget_id] = Budget(
            budget_id=budget_id,
            category_id=_text(payload, "category_id"),
            month=_month(payload, "month"),
            limit_minor_units=_positive_money(payload, field_name="limit_minor_units"),
            source_event_id=event.event_id,
        )
    elif event.event_type == "finance.recurring-entry-created":
        recurring_id = _text(payload, "recurring_entry_id")
        if recurring_id in recurring_entries:
            raise FinanceProjectionError("recurring entry already exists")
        ends_on = payload.get("ends_on")
        recurring_entries[recurring_id] = RecurringEntry(
            recurring_entry_id=recurring_id,
            direction=_direction(payload),
            category_id=_text(payload, "category_id"),
            amount_minor_units=_positive_money(payload),
            description=_text(payload, "description"),
            starts_on=_date(payload, "starts_on"),
            ends_on=_parse_date(ends_on) if ends_on is not None else None,
            active=True,
            source_event_id=event.event_id,
        )
    elif event.event_type == "finance.recurring-entry-deactivated":
        recurring_id = _text(payload, "recurring_entry_id")
        recurring = recurring_entries.get(recurring_id)
        if recurring is None or not recurring.active:
            raise FinanceProjectionError("recurring entry cannot be deactivated")
        recurring_entries[recurring_id] = replace(recurring, active=False)
    elif event.event_type == "finance.obligation-opened":
        obligation_id = _text(payload, "obligation_id")
        if obligation_id in obligations or event.contract_receipt is None:
            raise FinanceProjectionError("obligation requires a unique confirmed receipt")
        due_on = payload.get("due_on")
        obligations[obligation_id] = Obligation(
            obligation_id=obligation_id,
            direction=ObligationDirection(_text(payload, "direction")),
            amount_minor_units=_positive_money(payload),
            settled_minor_units=0,
            due_on=_parse_date(due_on) if due_on is not None else None,
            source_event_id=event.event_id,
            contract_receipt=event.contract_receipt,
        )
    elif event.event_type == "finance.obligation-settled":
        obligation_id = _text(payload, "obligation_id")
        obligation = obligations.get(obligation_id)
        if obligation is None or obligation.settled or event.contract_receipt is None:
            raise FinanceProjectionError("obligation cannot be settled")
        amount = _positive_money(payload, field_name="amount_minor_units")
        settled_minor_units = obligation.settled_minor_units + amount
        if settled_minor_units > obligation.amount_minor_units:
            raise FinanceProjectionError("obligation settlement exceeds outstanding amount")
        obligations[obligation_id] = replace(
            obligation,
            settled_minor_units=settled_minor_units,
            source_event_id=event.event_id,
            contract_receipt=event.contract_receipt,
        )
    else:
        raise FinanceProjectionError(f"unsupported finance event: {event.event_type}")

    return FinanceProjection(
        projection_version=event.aggregate_version,
        as_of_utc=event.occurred_at_utc.astimezone(UTC),
        categories=categories,
        transactions=transactions,
        budgets=budgets,
        recurring_entries=recurring_entries,
        obligations=obligations,
        source_event_ids=(*projection.source_event_ids, event.event_id),
    )


def summarize_month(
    projection: FinanceProjection, *, month: str
) -> MonthlyFinanceSummary:
    month_start, month_end = month_bounds(month)
    transactions = [
        entry
        for entry in projection.transactions.values()
        if not entry.voided and month_start <= entry.occurred_on <= month_end
    ]
    income = sum(
        entry.amount_minor_units
        for entry in transactions
        if entry.direction == EntryDirection.INCOME
    )
    expense = sum(
        entry.amount_minor_units
        for entry in transactions
        if entry.direction == EntryDirection.EXPENSE
    )
    matched_recurring = {
        entry.recurring_entry_id
        for entry in transactions
        if entry.recurring_entry_id is not None
    }
    outstanding_recurring = [
        entry
        for entry in projection.recurring_entries.values()
        if entry.active
        and entry.recurring_entry_id not in matched_recurring
        and entry.starts_on <= month_end
        and (entry.ends_on is None or entry.ends_on >= month_start)
    ]
    recurring_income = sum(
        entry.amount_minor_units
        for entry in outstanding_recurring
        if entry.direction == EntryDirection.INCOME
    )
    recurring_expense = sum(
        entry.amount_minor_units
        for entry in outstanding_recurring
        if entry.direction == EntryDirection.EXPENSE
    )
    due_obligations = [
        obligation
        for obligation in projection.obligations.values()
        if not obligation.settled
        and (
            obligation.due_on is None
            or month_start <= obligation.due_on <= month_end
        )
    ]
    receivable = sum(
        item.outstanding_minor_units
        for item in due_obligations
        if item.direction == ObligationDirection.RECEIVABLE
    )
    payable = sum(
        item.outstanding_minor_units
        for item in due_obligations
        if item.direction == ObligationDirection.PAYABLE
    )
    actual_savings = income - expense
    projected_savings = (
        actual_savings + recurring_income - recurring_expense + receivable - payable
    )
    all_time_balance = sum(
        entry.amount_minor_units
        if entry.direction == EntryDirection.INCOME
        else -entry.amount_minor_units
        for entry in projection.transactions.values()
        if not entry.voided
    )
    budget_statuses = _budget_statuses(
        projection, month=month, transactions=transactions
    )
    source_ids = tuple(
        sorted(
            {
                *(entry.source_event_id for entry in transactions),
                *(entry.source_event_id for entry in outstanding_recurring),
                *(entry.source_event_id for entry in due_obligations),
                *(
                    event_id
                    for status in budget_statuses
                    for event_id in status.source_event_ids
                ),
            }
        )
    )
    calculation_id = "savings_" + hashlib.sha256(
        _canonical_json_bytes(
            {
                "formula_version": SAVINGS_FORMULA_VERSION,
                "month": month,
                "projection_version": projection.projection_version,
                "source_event_ids": list(source_ids),
                "actual_savings_minor_units": actual_savings,
                "projected_savings_minor_units": projected_savings,
            }
        )
    ).hexdigest()[:32]
    return MonthlyFinanceSummary(
        month=month,
        income_minor_units=income,
        expense_minor_units=expense,
        balance_minor_units=all_time_balance,
        receivable_minor_units=receivable,
        payable_minor_units=payable,
        outstanding_recurring_income_minor_units=recurring_income,
        outstanding_recurring_expense_minor_units=recurring_expense,
        actual_savings_minor_units=actual_savings,
        projected_savings_minor_units=projected_savings,
        available_savings_minor_units=max(0, projected_savings),
        savings_formula_version=SAVINGS_FORMULA_VERSION,
        savings_calculation_id=calculation_id,
        projection_version=projection.projection_version,
        as_of_utc=projection.as_of_utc,
        source_event_ids=source_ids,
        budget_statuses=budget_statuses,
    )


def month_bounds(month: str) -> tuple[date, date]:
    if (
        len(month) != 7
        or month[4] != "-"
        or not month[:4].isdigit()
        or not month[5:].isdigit()
    ):
        raise FinanceProjectionError("month must use YYYY-MM")
    try:
        start = datetime.strptime(month, "%Y-%m").date().replace(day=1)
    except ValueError as exc:
        raise FinanceProjectionError("month must use YYYY-MM") from exc
    if start.month == 12:
        next_month = date(start.year + 1, 1, 1)
    else:
        next_month = date(start.year, start.month + 1, 1)
    return start, date.fromordinal(next_month.toordinal() - 1)


def _budget_statuses(
    projection: FinanceProjection,
    *,
    month: str,
    transactions: list[Transaction],
) -> tuple[BudgetStatus, ...]:
    results: list[BudgetStatus] = []
    for budget in sorted(
        (value for value in projection.budgets.values() if value.month == month),
        key=lambda value: value.budget_id,
    ):
        matching = [
            entry
            for entry in transactions
            if entry.direction == EntryDirection.EXPENSE
            and entry.category_id == budget.category_id
        ]
        spent = sum(entry.amount_minor_units for entry in matching)
        utilization = spent * 10_000 // budget.limit_minor_units
        status: Literal["on_track", "near_limit", "over_budget"] = (
            "over_budget"
            if spent > budget.limit_minor_units
            else "near_limit"
            if utilization >= 8_000
            else "on_track"
        )
        category = projection.categories.get(budget.category_id)
        results.append(
            BudgetStatus(
                budget_id=budget.budget_id,
                category_id=budget.category_id,
                category_name=category.name if category is not None else "Unknown",
                limit_minor_units=budget.limit_minor_units,
                spent_minor_units=spent,
                remaining_minor_units=max(0, budget.limit_minor_units - spent),
                utilization_basis_points=utilization,
                status=status,
                source_event_ids=(
                    budget.source_event_id,
                    *(entry.source_event_id for entry in matching),
                ),
            )
        )
    return tuple(results)


def _text(payload: dict[str, object], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value:
        raise FinanceProjectionError(f"{name} must be non-empty text")
    return value


def _direction(payload: dict[str, object]) -> EntryDirection:
    try:
        return EntryDirection(_text(payload, "direction"))
    except ValueError as exc:
        raise FinanceProjectionError("direction is invalid") from exc


def _positive_money(
    payload: dict[str, object], *, field_name: str = "amount_minor_units"
) -> int:
    if payload.get("currency") != "USD":
        raise FinanceProjectionError("currency must be USD")
    value = payload.get(field_name)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise FinanceProjectionError(f"{field_name} must be a positive integer")
    return value


def _date(payload: dict[str, object], name: str) -> date:
    return _parse_date(payload.get(name))


def _parse_date(value: object) -> date:
    if not isinstance(value, str):
        raise FinanceProjectionError("date must be ISO 8601 text")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise FinanceProjectionError("date must use YYYY-MM-DD") from exc


def _month(payload: dict[str, object], name: str) -> str:
    value = _text(payload, name)
    month_bounds(value)
    return value


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
