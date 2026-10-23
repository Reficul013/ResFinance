from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from typing import Annotated, Literal, NoReturn
from urllib.parse import urlsplit

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from server.app.application.authentication import (
    AccessPrincipal,
    AuthenticationService,
    AuthRejected,
    OriginRejected,
    SessionUnauthorized,
)
from server.app.application.finance import FinanceOverview, FinanceRejected, FinanceService
from server.app.domain.events import AppendResult
from server.app.domain.finance import EntryDirection
from server.app.infrastructure.event_repository import (
    AggregateVersionConflict,
    IdempotencyConflict,
)


class MoneyModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: Literal["USD"] = "USD"
    minor_units: int


class CategoryCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    name: str = Field(min_length=1, max_length=80)
    direction: Literal["income", "expense"]
    expected_version: int = Field(ge=0)


class TransactionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    direction: Literal["income", "expense"]
    category_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    amount: MoneyModel
    occurred_on: date
    description: str = Field(min_length=1, max_length=160)
    recurring_entry_id: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
    )
    expected_version: int = Field(ge=0)


class VoidTransactionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=160)
    expected_version: int = Field(ge=0)


class BudgetCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    budget_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    category_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    limit: MoneyModel
    expected_version: int = Field(ge=0)


class DeactivateBudgetCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=0)


class RecurringEntryCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recurring_entry_id: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
    )
    direction: Literal["income", "expense"]
    category_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    amount: MoneyModel
    description: str = Field(min_length=1, max_length=160)
    cadence: Literal["monthly"] = "monthly"
    starts_on: date
    ends_on: date | None = None
    expected_version: int = Field(ge=0)


class DeactivateRecurringCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=0)


class EventResponse(BaseModel):
    event_id: str
    projection_version: int
    occurred_at_utc: datetime
    deduplicated: bool
    receipt_ids: list[str]


class CategoryModel(BaseModel):
    category_id: str
    name: str
    direction: Literal["income", "expense"]
    active: bool
    source_event_id: str


class TransactionModel(BaseModel):
    transaction_id: str
    direction: Literal["income", "expense"]
    category_id: str
    amount: MoneyModel
    occurred_on: date
    description: str
    recurring_entry_id: str | None
    voided: bool
    source_event_id: str


class BudgetModel(BaseModel):
    budget_id: str
    category_id: str
    month: str
    limit: MoneyModel
    active: bool
    source_event_id: str


class RecurringEntryModel(BaseModel):
    recurring_entry_id: str
    direction: Literal["income", "expense"]
    category_id: str
    amount: MoneyModel
    description: str
    cadence: Literal["monthly"] = "monthly"
    starts_on: date
    ends_on: date | None
    active: bool
    source_event_id: str


class ObligationModel(BaseModel):
    obligation_id: str
    direction: Literal["receivable", "payable"]
    amount: MoneyModel
    settled_amount: MoneyModel
    outstanding_amount: MoneyModel
    due_on: date | None
    settled: bool
    source_event_id: str
    contract_receipt: str


class BudgetStatusModel(BaseModel):
    budget_id: str
    category_id: str
    category_name: str
    limit: MoneyModel
    spent: MoneyModel
    remaining: MoneyModel
    utilization_basis_points: int
    status: Literal["on_track", "near_limit", "over_budget"]
    source_event_ids: list[str]


class SavingsModel(BaseModel):
    actual: MoneyModel
    projected: MoneyModel
    available: MoneyModel
    formula_version: Literal["finance-savings-v1"]
    calculation_id: str
    source_event_ids: list[str]


class MonthlySummaryModel(BaseModel):
    month: str
    income: MoneyModel
    expense: MoneyModel
    balance: MoneyModel
    receivable: MoneyModel
    payable: MoneyModel
    outstanding_recurring_income: MoneyModel
    outstanding_recurring_expense: MoneyModel
    savings: SavingsModel
    budget_statuses: list[BudgetStatusModel]


class ProvenanceModel(BaseModel):
    projection_version: int
    as_of_utc: datetime | None
    source_event_ids: list[str]


class FinanceOverviewModel(BaseModel):
    summary: MonthlySummaryModel
    categories: list[CategoryModel]
    transactions: list[TransactionModel]
    budgets: list[BudgetModel]
    recurring_entries: list[RecurringEntryModel]
    obligations: list[ObligationModel]
    provenance: ProvenanceModel


def create_finance_router(
    service: FinanceService | None,
    auth_service: AuthenticationService | None,
) -> APIRouter:
    router = APIRouter(prefix="/finance", tags=["finance"])

    def services() -> tuple[FinanceService, AuthenticationService]:
        if service is None or auth_service is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="finance persistence is not configured",
            )
        return service, auth_service

    def principal(
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
        origin: Annotated[str | None, Header(alias="Origin")] = None,
        referer: Annotated[str | None, Header(alias="Referer")] = None,
    ) -> AccessPrincipal:
        _, authentication = services()
        prefix = "Bearer "
        if (
            authorization is None
            or not authorization.startswith(prefix)
            or len(authorization) <= len(prefix)
        ):
            raise HTTPException(status_code=401, detail="bearer token is required")
        request_origin = origin or _origin_from_referer(referer)
        if request_origin is None:
            raise HTTPException(
                status_code=403,
                detail="request origin or same-origin referrer is required",
            )
        try:
            return authentication.authenticate_access_token(
                access_token=authorization[len(prefix) :],
                origin=request_origin,
            )
        except AuthRejected as exc:
            _raise_auth_error(exc)

    @router.get("/overview", response_model=FinanceOverviewModel)
    def overview(
        month: str,
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
        origin: Annotated[str | None, Header(alias="Origin")] = None,
        referer: Annotated[str | None, Header(alias="Referer")] = None,
    ) -> FinanceOverviewModel:
        finance, _ = services()
        actor = principal(authorization, origin, referer)
        try:
            result = finance.overview(actor_address=actor.actor_address, month=month)
        except FinanceRejected as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _overview_response(result)

    @router.post("/categories", response_model=EventResponse, status_code=201)
    def create_category(
        request: CategoryCommand,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
        origin: Annotated[str | None, Header(alias="Origin")] = None,
    ) -> EventResponse:
        finance, _ = services()
        actor = principal(authorization, origin)
        return _run_command(
            lambda: finance.create_category(
                actor_address=actor.actor_address,
                idempotency_key=idempotency_key,
                expected_version=request.expected_version,
                category_id=request.category_id,
                name=request.name,
                direction=EntryDirection(request.direction),
            )
        )

    @router.post("/transactions", response_model=EventResponse, status_code=201)
    def record_transaction(
        request: TransactionCommand,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
        origin: Annotated[str | None, Header(alias="Origin")] = None,
    ) -> EventResponse:
        finance, _ = services()
        actor = principal(authorization, origin)
        return _run_command(
            lambda: finance.record_transaction(
                actor_address=actor.actor_address,
                idempotency_key=idempotency_key,
                expected_version=request.expected_version,
                transaction_id=request.transaction_id,
                direction=EntryDirection(request.direction),
                category_id=request.category_id,
                amount_minor_units=request.amount.minor_units,
                occurred_on=request.occurred_on,
                description=request.description,
                recurring_entry_id=request.recurring_entry_id,
            )
        )

    @router.post(
        "/transactions/{transaction_id}/void",
        response_model=EventResponse,
        status_code=201,
    )
    def void_transaction(
        transaction_id: str,
        request: VoidTransactionCommand,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
        origin: Annotated[str | None, Header(alias="Origin")] = None,
    ) -> EventResponse:
        finance, _ = services()
        actor = principal(authorization, origin)
        return _run_command(
            lambda: finance.void_transaction(
                actor_address=actor.actor_address,
                idempotency_key=idempotency_key,
                expected_version=request.expected_version,
                transaction_id=transaction_id,
                reason=request.reason,
            )
        )

    @router.post("/budgets", response_model=EventResponse, status_code=201)
    def set_budget(
        request: BudgetCommand,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
        origin: Annotated[str | None, Header(alias="Origin")] = None,
    ) -> EventResponse:
        finance, _ = services()
        actor = principal(authorization, origin)
        return _run_command(
            lambda: finance.set_budget(
                actor_address=actor.actor_address,
                idempotency_key=idempotency_key,
                expected_version=request.expected_version,
                budget_id=request.budget_id,
                category_id=request.category_id,
                month=request.month,
                limit_minor_units=request.limit.minor_units,
            )
        )

    @router.post(
        "/budgets/{budget_id}/deactivate",
        response_model=EventResponse,
        status_code=201,
    )
    def deactivate_budget(
        budget_id: str,
        request: DeactivateBudgetCommand,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
        origin: Annotated[str | None, Header(alias="Origin")] = None,
    ) -> EventResponse:
        finance, _ = services()
        actor = principal(authorization, origin)
        return _run_command(
            lambda: finance.deactivate_budget(
                actor_address=actor.actor_address,
                idempotency_key=idempotency_key,
                expected_version=request.expected_version,
                budget_id=budget_id,
            )
        )

    @router.post("/recurring", response_model=EventResponse, status_code=201)
    def create_recurring_entry(
        request: RecurringEntryCommand,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
        origin: Annotated[str | None, Header(alias="Origin")] = None,
    ) -> EventResponse:
        finance, _ = services()
        actor = principal(authorization, origin)
        return _run_command(
            lambda: finance.create_recurring_entry(
                actor_address=actor.actor_address,
                idempotency_key=idempotency_key,
                expected_version=request.expected_version,
                recurring_entry_id=request.recurring_entry_id,
                direction=EntryDirection(request.direction),
                category_id=request.category_id,
                amount_minor_units=request.amount.minor_units,
                description=request.description,
                starts_on=request.starts_on,
                ends_on=request.ends_on,
            )
        )

    @router.post(
        "/recurring/{recurring_entry_id}/deactivate",
        response_model=EventResponse,
        status_code=201,
    )
    def deactivate_recurring_entry(
        recurring_entry_id: str,
        request: DeactivateRecurringCommand,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
        origin: Annotated[str | None, Header(alias="Origin")] = None,
    ) -> EventResponse:
        finance, _ = services()
        actor = principal(authorization, origin)
        return _run_command(
            lambda: finance.deactivate_recurring_entry(
                actor_address=actor.actor_address,
                idempotency_key=idempotency_key,
                expected_version=request.expected_version,
                recurring_entry_id=recurring_entry_id,
            )
        )

    return router


def _run_command(command: Callable[[], AppendResult]) -> EventResponse:
    try:
        result = command()
    except IdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AggregateVersionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except FinanceRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not isinstance(result, AppendResult):
        raise RuntimeError("finance command returned an unexpected result")
    return _event_response(result)


def _event_response(result: AppendResult) -> EventResponse:
    return EventResponse(
        event_id=result.event.event_id,
        projection_version=result.event.aggregate_version,
        occurred_at_utc=result.event.occurred_at_utc,
        deduplicated=result.deduplicated,
        receipt_ids=(
            [result.event.contract_receipt]
            if result.event.contract_receipt is not None
            else []
        ),
    )


def _overview_response(value: FinanceOverview) -> FinanceOverviewModel:
    projection = value.projection
    summary = value.summary
    return FinanceOverviewModel(
        summary=MonthlySummaryModel(
            month=summary.month,
            income=_money(summary.income_minor_units),
            expense=_money(summary.expense_minor_units),
            balance=_money(summary.balance_minor_units),
            receivable=_money(summary.receivable_minor_units),
            payable=_money(summary.payable_minor_units),
            outstanding_recurring_income=_money(
                summary.outstanding_recurring_income_minor_units
            ),
            outstanding_recurring_expense=_money(
                summary.outstanding_recurring_expense_minor_units
            ),
            savings=SavingsModel(
                actual=_money(summary.actual_savings_minor_units),
                projected=_money(summary.projected_savings_minor_units),
                available=_money(summary.available_savings_minor_units),
                formula_version="finance-savings-v1",
                calculation_id=summary.savings_calculation_id,
                source_event_ids=list(summary.source_event_ids),
            ),
            budget_statuses=[
                BudgetStatusModel(
                    budget_id=item.budget_id,
                    category_id=item.category_id,
                    category_name=item.category_name,
                    limit=_money(item.limit_minor_units),
                    spent=_money(item.spent_minor_units),
                    remaining=_money(item.remaining_minor_units),
                    utilization_basis_points=item.utilization_basis_points,
                    status=item.status,
                    source_event_ids=list(item.source_event_ids),
                )
                for item in summary.budget_statuses
            ],
        ),
        categories=[
            CategoryModel(
                category_id=item.category_id,
                name=item.name,
                direction=item.direction.value,
                active=item.active,
                source_event_id=item.source_event_id,
            )
            for item in sorted(
                projection.categories.values(), key=lambda item: item.name.casefold()
            )
        ],
        transactions=[
            TransactionModel(
                transaction_id=item.transaction_id,
                direction=item.direction.value,
                category_id=item.category_id,
                amount=_money(item.amount_minor_units),
                occurred_on=item.occurred_on,
                description=item.description,
                recurring_entry_id=item.recurring_entry_id,
                voided=item.voided,
                source_event_id=item.source_event_id,
            )
            for item in sorted(
                projection.transactions.values(),
                key=lambda item: (item.occurred_on, item.transaction_id),
                reverse=True,
            )
        ],
        budgets=[
            BudgetModel(
                budget_id=item.budget_id,
                category_id=item.category_id,
                month=item.month,
                limit=_money(item.limit_minor_units),
                active=item.active,
                source_event_id=item.source_event_id,
            )
            for item in sorted(
                projection.budgets.values(), key=lambda item: item.budget_id
            )
        ],
        recurring_entries=[
            RecurringEntryModel(
                recurring_entry_id=item.recurring_entry_id,
                direction=item.direction.value,
                category_id=item.category_id,
                amount=_money(item.amount_minor_units),
                description=item.description,
                starts_on=item.starts_on,
                ends_on=item.ends_on,
                active=item.active,
                source_event_id=item.source_event_id,
            )
            for item in sorted(
                projection.recurring_entries.values(),
                key=lambda item: item.recurring_entry_id,
            )
        ],
        obligations=[
            ObligationModel(
                obligation_id=item.obligation_id,
                direction=item.direction.value,
                amount=_money(item.amount_minor_units),
                settled_amount=_money(item.settled_minor_units),
                outstanding_amount=_money(item.outstanding_minor_units),
                due_on=item.due_on,
                settled=item.settled,
                source_event_id=item.source_event_id,
                contract_receipt=item.contract_receipt,
            )
            for item in sorted(
                projection.obligations.values(), key=lambda item: item.obligation_id
            )
        ],
        provenance=ProvenanceModel(
            projection_version=projection.projection_version,
            as_of_utc=projection.as_of_utc,
            source_event_ids=list(projection.source_event_ids),
        ),
    )


def _money(minor_units: int) -> MoneyModel:
    return MoneyModel(minor_units=minor_units)


def _origin_from_referer(referer: str | None) -> str | None:
    if referer is None:
        return None
    parsed = urlsplit(referer)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def _raise_auth_error(exc: AuthRejected) -> NoReturn:
    status_code = 403 if isinstance(exc, OriginRejected) else 401
    if not isinstance(exc, OriginRejected | SessionUnauthorized):
        status_code = 422
    raise HTTPException(status_code=status_code, detail=str(exc)) from exc
