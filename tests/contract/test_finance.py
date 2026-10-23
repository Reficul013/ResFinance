from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

from server.app.application.finance import FinanceRejected, FinanceService
from server.app.domain.finance import EntryDirection, ObligationDirection
from server.app.infrastructure.encryption import AesGcmCipher
from server.app.infrastructure.event_repository import (
    AggregateVersionConflict,
    EncryptedEventRepository,
)
from server.app.main import create_app
from tests.contract.test_authentication import (
    ORIGIN,
    challenge,
    create_session,
    login_intent,
    wallet,
)
from tests.contract.test_authentication import (
    service as auth_service,
)

NOW = datetime(2026, 10, 14, 8, 0, tzinfo=UTC)
ACTOR = "0x" + "a" * 40


class MemoryKeyValueStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def put(self, key: str, value: str) -> None:
        self.values[key] = value

    def range_values(self, prefix: str) -> Sequence[str]:
        return [self.values[key] for key in sorted(self.values) if key.startswith(prefix)]


def finance_service(store: MemoryKeyValueStore) -> FinanceService:
    return FinanceService(
        EncryptedEventRepository(
            store,
            AesGcmCipher(b"f" * 32, key_id="finance-test-v1"),
            clock=lambda: NOW,
        )
    )


def test_finance_projection_rebuilds_exact_savings_budgets_and_obligations() -> None:
    store = MemoryKeyValueStore()
    service = finance_service(store)

    service.create_category(
        actor_address=ACTOR,
        idempotency_key="category-income-0001",
        expected_version=0,
        category_id="salary",
        name="Salary",
        direction=EntryDirection.INCOME,
    )
    service.create_category(
        actor_address=ACTOR,
        idempotency_key="category-expense-0002",
        expected_version=1,
        category_id="groceries",
        name="Groceries",
        direction=EntryDirection.EXPENSE,
    )
    service.record_transaction(
        actor_address=ACTOR,
        idempotency_key="transaction-income-0003",
        expected_version=2,
        transaction_id="paycheck-october",
        direction=EntryDirection.INCOME,
        category_id="salary",
        amount_minor_units=500_000,
        occurred_on=date(2026, 10, 1),
        description="October salary",
        recurring_entry_id=None,
    )
    service.record_transaction(
        actor_address=ACTOR,
        idempotency_key="transaction-expense-0004",
        expected_version=3,
        transaction_id="groceries-october",
        direction=EntryDirection.EXPENSE,
        category_id="groceries",
        amount_minor_units=90_000,
        occurred_on=date(2026, 10, 10),
        description="October groceries",
        recurring_entry_id=None,
    )
    service.set_budget(
        actor_address=ACTOR,
        idempotency_key="budget-0005",
        expected_version=4,
        budget_id="groceries-2026-10",
        category_id="groceries",
        month="2026-10",
        limit_minor_units=100_000,
    )
    service.create_recurring_entry(
        actor_address=ACTOR,
        idempotency_key="recurring-0006",
        expected_version=5,
        recurring_entry_id="monthly-groceries",
        direction=EntryDirection.EXPENSE,
        category_id="groceries",
        amount_minor_units=150_000,
        description="Expected monthly groceries",
        starts_on=date(2026, 1, 1),
        ends_on=None,
    )
    service.record_confirmed_obligation(
        actor_address=ACTOR,
        idempotency_key="obligation-0007",
        expected_version=6,
        obligation_id="group-payable-1",
        direction=ObligationDirection.PAYABLE,
        amount_minor_units=20_000,
        due_on=date(2026, 10, 20),
        source_event_id="group-event-0001",
        contract_receipt="contract-receipt-0001",
    )
    service.record_confirmed_obligation(
        actor_address=ACTOR,
        idempotency_key="obligation-0008",
        expected_version=7,
        obligation_id="group-receivable-1",
        direction=ObligationDirection.RECEIVABLE,
        amount_minor_units=30_000,
        due_on=date(2026, 10, 22),
        source_event_id="group-event-0002",
        contract_receipt="contract-receipt-0002",
    )

    overview = service.overview(actor_address=ACTOR, month="2026-10")
    summary = overview.summary
    assert summary.income_minor_units == 500_000
    assert summary.expense_minor_units == 90_000
    assert summary.balance_minor_units == 410_000
    assert summary.actual_savings_minor_units == 410_000
    assert summary.outstanding_recurring_expense_minor_units == 150_000
    assert summary.payable_minor_units == 20_000
    assert summary.receivable_minor_units == 30_000
    assert summary.projected_savings_minor_units == 270_000
    assert summary.available_savings_minor_units == 270_000
    assert summary.savings_formula_version == "finance-savings-v1"
    assert summary.savings_calculation_id.startswith("savings_")
    assert summary.projection_version == 8
    assert summary.budget_statuses[0].status == "near_limit"
    assert summary.budget_statuses[0].utilization_basis_points == 9_000

    restarted = finance_service(store).overview(
        actor_address=ACTOR, month="2026-10"
    )
    assert restarted.summary == summary
    other_wallet = service.overview(
        actor_address="0x" + "b" * 40, month="2026-10"
    )
    assert other_wallet.projection.projection_version == 0
    assert other_wallet.summary.balance_minor_units == 0
    persisted = "".join(store.values.values())
    assert "October salary" not in persisted
    assert "Expected monthly groceries" not in persisted


def test_finance_writes_are_idempotent_versioned_and_compensating() -> None:
    store = MemoryKeyValueStore()
    service = finance_service(store)
    first = service.create_category(
        actor_address=ACTOR,
        idempotency_key="category-income-0001",
        expected_version=0,
        category_id="income",
        name="Income",
        direction=EntryDirection.INCOME,
    )
    duplicate = service.create_category(
        actor_address=ACTOR,
        idempotency_key="category-income-0001",
        expected_version=0,
        category_id="income",
        name="Income",
        direction=EntryDirection.INCOME,
    )
    assert duplicate.deduplicated
    assert duplicate.event.event_id == first.event.event_id

    with pytest.raises(AggregateVersionConflict):
        service.create_category(
            actor_address=ACTOR,
            idempotency_key="stale-category-0002",
            expected_version=0,
            category_id="other",
            name="Other",
            direction=EntryDirection.INCOME,
        )

    transaction = service.record_transaction(
        actor_address=ACTOR,
        idempotency_key="transaction-0003",
        expected_version=1,
        transaction_id="deposit",
        direction=EntryDirection.INCOME,
        category_id="income",
        amount_minor_units=10_000,
        occurred_on=date(2026, 10, 1),
        description="Deposit",
        recurring_entry_id=None,
    )
    service.void_transaction(
        actor_address=ACTOR,
        idempotency_key="void-transaction-0004",
        expected_version=2,
        transaction_id="deposit",
        reason="Entered twice",
    )
    overview = service.overview(actor_address=ACTOR, month="2026-10")
    assert overview.summary.balance_minor_units == 0
    assert overview.projection.transactions["deposit"].voided
    assert overview.projection.projection_version == 3
    assert transaction.event.event_id in overview.projection.source_event_ids

    with pytest.raises(FinanceRejected):
        service.record_transaction(
            actor_address=ACTOR,
            idempotency_key="negative-transaction-0005",
            expected_version=3,
            transaction_id="bad",
            direction=EntryDirection.INCOME,
            category_id="income",
            amount_minor_units=-1,
            occurred_on=date(2026, 10, 1),
            description="Bad",
            recurring_entry_id=None,
        )


def test_authenticated_finance_api_exposes_projection_and_provenance() -> None:
    store = MemoryKeyValueStore()
    authentication = auth_service(store)
    finance = finance_service(store)
    client = TestClient(create_app(authentication, finance))
    private_key, identity = wallet()
    challenge_body = challenge(client, identity)
    session = create_session(
        client,
        challenge_body,
        login_intent(private_key, identity, challenge_body),
    )
    token = session.json()["access_token"]
    headers = {
        "Origin": ORIGIN,
        "Authorization": f"Bearer {token}",
        "Idempotency-Key": "api-category-0001",
    }
    command = {
        "category_id": "salary",
        "name": "Salary",
        "direction": "income",
        "expected_version": 0,
    }

    created = client.post("/api/v1/finance/categories", headers=headers, json=command)
    duplicate = client.post(
        "/api/v1/finance/categories", headers=headers, json=command
    )
    assert created.status_code == 201
    assert duplicate.status_code == 201
    assert duplicate.json()["deduplicated"] is True

    budget = client.post(
        "/api/v1/finance/budgets",
        headers={**headers, "Idempotency-Key": "api-budget-0002"},
        json={
            "budget_id": "rent-2026-10",
            "category_id": "rent",
            "month": "2026-10",
            "limit": {"currency": "USD", "minor_units": 150_000},
            "expected_version": 1,
        },
    )
    removed = client.post(
        "/api/v1/finance/budgets/rent-2026-10/deactivate",
        headers={**headers, "Idempotency-Key": "api-budget-remove-0003"},
        json={"expected_version": 2},
    )
    assert budget.status_code == 201
    assert removed.status_code == 201

    overview = client.get(
        "/api/v1/finance/overview?month=2026-10",
        headers={"Origin": ORIGIN, "Authorization": f"Bearer {token}"},
    )
    assert overview.status_code == 200
    body = overview.json()
    assert body["provenance"]["projection_version"] == 3
    assert {item["name"] for item in body["categories"]} >= {
        "Salary",
        "Liquid Funds Transfer",
        "Other Sources",
        "Rent",
        "Utilities",
        "Shopping",
        "Entertainment",
        "Food & Groceries",
        "Medical Bills",
        "Miscellaneous",
    }
    assert body["summary"]["savings"]["formula_version"] == "finance-savings-v1"
    assert len(body["provenance"]["source_event_ids"]) == 3
    assert body["budgets"] == [
        {
            "budget_id": "rent-2026-10",
            "category_id": "rent",
            "month": "2026-10",
            "limit": {"currency": "USD", "minor_units": 150_000},
            "active": False,
            "source_event_id": budget.json()["event_id"],
        }
    ]
    assert body["summary"]["budget_statuses"] == []

    unauthorized = client.get("/api/v1/finance/overview?month=2026-10")
    assert unauthorized.status_code == 401


def test_deterministic_categories_are_available_without_category_events() -> None:
    service = finance_service(MemoryKeyValueStore())

    initial = service.overview(actor_address=ACTOR, month="2026-10")
    assert initial.projection.projection_version == 0
    assert [
        category.name
        for category in initial.projection.categories.values()
        if category.direction == EntryDirection.INCOME
    ] == ["Salary", "Liquid Funds Transfer", "Other Sources"]

    service.record_transaction(
        actor_address=ACTOR,
        idempotency_key="deterministic-rent-0001",
        expected_version=0,
        transaction_id="rent-october",
        direction=EntryDirection.EXPENSE,
        category_id="rent",
        amount_minor_units=120_000,
        occurred_on=date(2026, 10, 1),
        description="October rent",
        recurring_entry_id=None,
    )
    overview = service.overview(actor_address=ACTOR, month="2026-10")
    assert overview.summary.expense_minor_units == 120_000

    service.set_budget(
        actor_address=ACTOR,
        idempotency_key="deterministic-budget-0002",
        expected_version=1,
        budget_id="rent-2026-10",
        category_id="rent",
        month="2026-10",
        limit_minor_units=150_000,
    )
    service.create_recurring_entry(
        actor_address=ACTOR,
        idempotency_key="deterministic-income-0003",
        expected_version=2,
        recurring_entry_id="monthly-salary",
        direction=EntryDirection.INCOME,
        category_id="salary",
        amount_minor_units=500_000,
        description="Monthly salary",
        starts_on=date(2026, 10, 1),
        ends_on=None,
    )
    overview = service.overview(actor_address=ACTOR, month="2026-10")
    assert overview.summary.budget_statuses[0].category_name == "Rent"
    assert overview.summary.outstanding_recurring_income_minor_units == 500_000

    service.deactivate_budget(
        actor_address=ACTOR,
        idempotency_key="deterministic-budget-remove-0004",
        expected_version=3,
        budget_id="rent-2026-10",
    )
    overview = service.overview(actor_address=ACTOR, month="2026-10")
    assert not overview.projection.budgets["rent-2026-10"].active
    assert overview.summary.budget_statuses == ()

    with pytest.raises(FinanceRejected, match="direction does not match category"):
        service.record_transaction(
            actor_address=ACTOR,
            idempotency_key="wrong-category-direction-0004",
            expected_version=4,
            transaction_id="invalid-rent-income",
            direction=EntryDirection.INCOME,
            category_id="rent",
            amount_minor_units=1_000,
            occurred_on=date(2026, 10, 2),
            description="Invalid direction",
            recurring_entry_id=None,
        )
