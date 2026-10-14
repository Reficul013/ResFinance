from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from typing import Annotated, Literal, NoReturn
from urllib.parse import urlsplit

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from server.app.api.finance import EventResponse, MoneyModel
from server.app.application.authentication import (
    AccessPrincipal,
    AuthenticationService,
    AuthRejected,
    OriginRejected,
    SessionUnauthorized,
)
from server.app.application.groups import GroupRejected, GroupService
from server.app.domain.events import AppendResult
from server.app.domain.groups import GroupProjection
from server.app.domain.settlement import SignedIntent
from server.app.infrastructure.event_repository import (
    AggregateVersionConflict,
    IdempotencyConflict,
)

_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
_ADDRESS_PATTERN = r"^0x[0-9a-fA-F]{40}$"


class SignedIntentModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1]
    intent_id: str = Field(min_length=1, max_length=128)
    action: Literal["split.approve", "credits.fund", "settlement.authorize"]
    actor_public_key: str
    actor_address: str = Field(pattern=_ADDRESS_PATTERN)
    resource_id: str = Field(pattern=_ID_PATTERN)
    parameters_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    nonce: str = Field(min_length=16, max_length=128)
    issued_at: datetime
    expires_at: datetime
    origin: str
    audience: Literal["resfinance-api"]
    network_id: Literal["pinned-local-network"]
    signature: str


class CreateGroupCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_id: str = Field(pattern=_ID_PATTERN)
    name: str = Field(min_length=1, max_length=80)
    owner_display_name: str = Field(min_length=1, max_length=80)
    expected_version: int = Field(ge=0)


class AddMemberCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    member_address: str = Field(pattern=_ADDRESS_PATTERN)
    display_name: str = Field(min_length=1, max_length=80)
    expected_version: int = Field(ge=0)


class CreateExpenseCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expense_id: str = Field(pattern=_ID_PATTERN)
    payer_address: str = Field(pattern=_ADDRESS_PATTERN)
    description: str = Field(min_length=1, max_length=160)
    amount: MoneyModel
    occurred_on: date
    due_on: date | None = None
    shares: dict[str, MoneyModel] = Field(min_length=1)
    expected_version: int = Field(ge=0)
    intent: SignedIntentModel


class ObligationDecisionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
    expected_version: int = Field(ge=0)
    intent: SignedIntentModel


class FundCreditsCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: MoneyModel
    expected_version: int = Field(ge=0)
    intent: SignedIntentModel


class SettleObligationCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: MoneyModel
    expected_version: int = Field(ge=0)
    intent: SignedIntentModel


class GroupSummaryModel(BaseModel):
    group_id: str
    name: str
    member_count: int
    open_obligation_count: int
    projection_version: int


class GroupMemberModel(BaseModel):
    actor_address: str
    display_name: str
    active: bool
    source_event_id: str


class GroupExpenseModel(BaseModel):
    expense_id: str
    payer_address: str
    description: str
    amount: MoneyModel
    occurred_on: date
    shares: dict[str, MoneyModel]
    obligation_ids: list[str]
    source_event_id: str
    contract_receipts: list[str]


class GroupObligationModel(BaseModel):
    obligation_id: str
    expense_id: str
    creditor_address: str
    debtor_address: str
    amount: MoneyModel
    settled_amount: MoneyModel
    outstanding_amount: MoneyModel
    due_on: date | None
    status: Literal[
        "pending", "open", "partially_settled", "settled", "rejected", "cancelled"
    ]
    source_event_id: str
    contract_receipts: list[str]


class NotificationModel(BaseModel):
    notification_id: str
    recipient_address: str
    kind: str
    message: str
    source_event_id: str


class GroupProvenanceModel(BaseModel):
    projection_version: int
    as_of_utc: datetime | None
    source_event_ids: list[str]


class GroupOverviewModel(BaseModel):
    group_id: str
    name: str
    owner_address: str
    members: list[GroupMemberModel]
    expenses: list[GroupExpenseModel]
    obligations: list[GroupObligationModel]
    credit_balances: dict[str, MoneyModel]
    notifications: list[NotificationModel]
    provenance: GroupProvenanceModel
    credit_disclaimer: Literal[
        "Internal credits are non-redeemable, non-monetary, and have no cash value."
    ]


def create_groups_router(
    service: GroupService | None,
    auth_service: AuthenticationService | None,
) -> APIRouter:
    router = APIRouter(prefix="/groups", tags=["groups"])

    def services() -> tuple[GroupService, AuthenticationService]:
        if service is None or auth_service is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="group settlement is not configured",
            )
        return service, auth_service

    def principal(
        authorization: str | None,
        origin: str | None,
        referer: str | None = None,
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
                access_token=authorization[len(prefix) :], origin=request_origin
            )
        except AuthRejected as exc:
            _raise_auth_error(exc)

    @router.get("", response_model=list[GroupSummaryModel])
    def list_groups(
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
        origin: Annotated[str | None, Header(alias="Origin")] = None,
        referer: Annotated[str | None, Header(alias="Referer")] = None,
    ) -> list[GroupSummaryModel]:
        groups, _ = services()
        actor = principal(authorization, origin, referer)
        return [_summary(value) for value in groups.list_groups(actor_address=actor.actor_address)]

    @router.post("", response_model=EventResponse, status_code=201)
    def create_group(
        request: CreateGroupCommand,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
        origin: Annotated[str | None, Header(alias="Origin")] = None,
    ) -> EventResponse:
        groups, _ = services()
        actor = principal(authorization, origin)
        return _run_command(
            lambda: groups.create_group(
                actor_address=actor.actor_address,
                idempotency_key=idempotency_key,
                expected_version=request.expected_version,
                group_id=request.group_id,
                name=request.name,
                owner_display_name=request.owner_display_name,
            )
        )

    @router.get("/{group_id}", response_model=GroupOverviewModel)
    def overview(
        group_id: str,
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
        origin: Annotated[str | None, Header(alias="Origin")] = None,
        referer: Annotated[str | None, Header(alias="Referer")] = None,
    ) -> GroupOverviewModel:
        groups, _ = services()
        actor = principal(authorization, origin, referer)
        try:
            value = groups.overview(actor_address=actor.actor_address, group_id=group_id)
        except GroupRejected as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _overview(value, actor.actor_address)

    @router.post("/{group_id}/members", response_model=EventResponse, status_code=201)
    def add_member(
        group_id: str,
        request: AddMemberCommand,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
        origin: Annotated[str | None, Header(alias="Origin")] = None,
    ) -> EventResponse:
        groups, _ = services()
        actor = principal(authorization, origin)
        return _run_command(
            lambda: groups.add_member(
                actor_address=actor.actor_address,
                idempotency_key=idempotency_key,
                expected_version=request.expected_version,
                group_id=group_id,
                member_address=request.member_address,
                display_name=request.display_name,
            )
        )

    @router.post("/{group_id}/expenses", response_model=EventResponse, status_code=201)
    def create_expense(
        group_id: str,
        request: CreateExpenseCommand,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
        origin: Annotated[str | None, Header(alias="Origin")] = None,
    ) -> EventResponse:
        groups, _ = services()
        actor = principal(authorization, origin)
        if origin is None:
            raise HTTPException(status_code=403, detail="Origin is required for signing")
        return _run_command(
            lambda: groups.create_expense(
                actor_address=actor.actor_address,
                idempotency_key=idempotency_key,
                expected_version=request.expected_version,
                group_id=group_id,
                expense_id=request.expense_id,
                payer_address=request.payer_address,
                description=request.description,
                amount_minor_units=request.amount.minor_units,
                occurred_on=request.occurred_on,
                due_on=request.due_on,
                shares={key: money.minor_units for key, money in request.shares.items()},
                intent=_intent(request.intent),
                origin=origin,
            )
        )

    @router.post(
        "/{group_id}/obligations/{obligation_id}/decision",
        response_model=EventResponse,
        status_code=201,
    )
    def decide_obligation(
        group_id: str,
        obligation_id: str,
        request: ObligationDecisionCommand,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
        origin: Annotated[str | None, Header(alias="Origin")] = None,
    ) -> EventResponse:
        groups, _ = services()
        actor = principal(authorization, origin)
        if origin is None:
            raise HTTPException(status_code=403, detail="Origin is required for signing")
        return _run_command(
            lambda: groups.decide_obligation(
                actor_address=actor.actor_address,
                idempotency_key=idempotency_key,
                expected_version=request.expected_version,
                group_id=group_id,
                obligation_id=obligation_id,
                approve=request.decision == "approve",
                intent=_intent(request.intent),
                origin=origin,
            )
        )

    @router.post("/{group_id}/credits", response_model=EventResponse, status_code=201)
    def fund_credits(
        group_id: str,
        request: FundCreditsCommand,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
        origin: Annotated[str | None, Header(alias="Origin")] = None,
    ) -> EventResponse:
        groups, _ = services()
        actor = principal(authorization, origin)
        if origin is None:
            raise HTTPException(status_code=403, detail="Origin is required for signing")
        return _run_command(
            lambda: groups.fund_credits(
                actor_address=actor.actor_address,
                idempotency_key=idempotency_key,
                expected_version=request.expected_version,
                group_id=group_id,
                amount_minor_units=request.amount.minor_units,
                intent=_intent(request.intent),
                origin=origin,
            )
        )

    @router.post(
        "/{group_id}/obligations/{obligation_id}/settlements",
        response_model=EventResponse,
        status_code=201,
    )
    def settle_obligation(
        group_id: str,
        obligation_id: str,
        request: SettleObligationCommand,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
        origin: Annotated[str | None, Header(alias="Origin")] = None,
    ) -> EventResponse:
        groups, _ = services()
        actor = principal(authorization, origin)
        if origin is None:
            raise HTTPException(status_code=403, detail="Origin is required for signing")
        return _run_command(
            lambda: groups.settle_obligation(
                actor_address=actor.actor_address,
                idempotency_key=idempotency_key,
                expected_version=request.expected_version,
                group_id=group_id,
                obligation_id=obligation_id,
                amount_minor_units=request.amount.minor_units,
                intent=_intent(request.intent),
                origin=origin,
            )
        )

    return router


def _run_command(command: Callable[[], AppendResult]) -> EventResponse:
    try:
        result = command()
    except (IdempotencyConflict, AggregateVersionConflict) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except GroupRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
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


def _intent(value: SignedIntentModel) -> SignedIntent:
    return SignedIntent(**value.model_dump())


def _summary(value: GroupProjection) -> GroupSummaryModel:
    if value.group_id is None or value.name is None:
        raise RuntimeError("group projection is incomplete")
    return GroupSummaryModel(
        group_id=value.group_id,
        name=value.name,
        member_count=sum(member.active for member in value.members.values()),
        open_obligation_count=sum(
            item.status in {"open", "partially_settled"}
            for item in value.obligations.values()
        ),
        projection_version=value.projection_version,
    )


def _overview(value: GroupProjection, actor_address: str) -> GroupOverviewModel:
    if value.group_id is None or value.name is None or value.owner_address is None:
        raise RuntimeError("group projection is incomplete")
    return GroupOverviewModel(
        group_id=value.group_id,
        name=value.name,
        owner_address=value.owner_address,
        members=[
            GroupMemberModel(**member.__dict__)
            for member in sorted(value.members.values(), key=lambda item: item.actor_address)
        ],
        expenses=[
            GroupExpenseModel(
                expense_id=item.expense_id,
                payer_address=item.payer_address,
                description=item.description,
                amount=MoneyModel(minor_units=item.amount_minor_units),
                occurred_on=item.occurred_on,
                shares={key: MoneyModel(minor_units=amount) for key, amount in item.shares.items()},
                obligation_ids=list(item.obligation_ids),
                source_event_id=item.source_event_id,
                contract_receipts=list(item.contract_receipts),
            )
            for item in sorted(value.expenses.values(), key=lambda item: item.expense_id)
        ],
        obligations=[
            GroupObligationModel(
                obligation_id=item.obligation_id,
                expense_id=item.expense_id,
                creditor_address=item.creditor_address,
                debtor_address=item.debtor_address,
                amount=MoneyModel(minor_units=item.amount_minor_units),
                settled_amount=MoneyModel(minor_units=item.settled_minor_units),
                outstanding_amount=MoneyModel(minor_units=item.outstanding_minor_units),
                due_on=item.due_on,
                status=item.status.value,
                source_event_id=item.source_event_id,
                contract_receipts=list(item.contract_receipts),
            )
            for item in sorted(value.obligations.values(), key=lambda item: item.obligation_id)
        ],
        credit_balances={
            key: MoneyModel(minor_units=amount)
            for key, amount in sorted(value.credit_balances.items())
        },
        notifications=[
            NotificationModel(**item.__dict__)
            for item in value.notifications
            if item.recipient_address == actor_address
        ],
        provenance=GroupProvenanceModel(
            projection_version=value.projection_version,
            as_of_utc=value.as_of_utc,
            source_event_ids=list(value.source_event_ids),
        ),
        credit_disclaimer=(
            "Internal credits are non-redeemable, non-monetary, and have no cash value."
        ),
    )


def _origin_from_referer(referer: str | None) -> str | None:
    if referer is None:
        return None
    parsed = urlsplit(referer)
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        return None
    default = (parsed.scheme == "https" and parsed.port in {None, 443}) or (
        parsed.scheme == "http" and parsed.port in {None, 80}
    )
    return f"{parsed.scheme}://{parsed.hostname}" if default else f"{parsed.scheme}://{parsed.netloc}"


def _raise_auth_error(exc: AuthRejected) -> NoReturn:
    if isinstance(exc, SessionUnauthorized):
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    if isinstance(exc, OriginRejected):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    raise HTTPException(status_code=422, detail=str(exc)) from exc
