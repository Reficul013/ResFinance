from __future__ import annotations

from datetime import datetime
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
from server.app.application.insights import InsightsService
from server.app.domain.insights import (
    AuthorizedFact,
    InsightNotification,
    InsightResponse,
    InsightsOverview,
)


class InsightQueryModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    question: str = Field(min_length=1, max_length=500)


class EvidenceModel(BaseModel):
    fact_id: str
    topic: Literal["savings", "budgets", "obligations", "crypto", "general"]
    statement: str
    source_kind: str
    source_ids: list[str]
    as_of_utc: datetime | None


class InsightResponseModel(BaseModel):
    summary: str
    evidence: list[EvidenceModel]
    caveats: list[str]
    follow_up_questions: list[str]
    mode: Literal["local-model", "template-fallback", "refusal"]
    model_id: str
    model_revision: str
    refused: bool


class InsightNotificationModel(BaseModel):
    notification_id: str
    severity: Literal["info", "warning", "urgent"]
    title: str
    message: str
    href: Literal["/finance", "/groups", "/crypto", "/insights"]
    fact_ids: list[str]


class InsightsOverviewModel(BaseModel):
    month: str
    fact_bundle_id: str
    insight: InsightResponseModel
    notifications: list[InsightNotificationModel]


def create_insights_router(
    service: InsightsService | None,
    auth_service: AuthenticationService | None,
) -> APIRouter:
    router = APIRouter(prefix="/insights", tags=["insights"])

    def services() -> tuple[InsightsService, AuthenticationService]:
        if service is None or auth_service is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="read-only insights are not configured",
            )
        return service, auth_service

    def principal(
        authorization: str | None,
        origin: str | None,
        referer: str | None = None,
    ) -> AccessPrincipal:
        _, authentication = services()
        prefix = "Bearer "
        if authorization is None or not authorization.startswith(prefix):
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

    @router.get("/overview", response_model=InsightsOverviewModel)
    def overview(
        month: str,
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
        origin: Annotated[str | None, Header(alias="Origin")] = None,
        referer: Annotated[str | None, Header(alias="Referer")] = None,
    ) -> InsightsOverviewModel:
        insights, _ = services()
        actor = principal(authorization, origin, referer)
        try:
            result = insights.overview(actor_address=actor.actor_address, month=month)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _overview_response(result)

    @router.post("/query", response_model=InsightResponseModel)
    def query(
        request: InsightQueryModel,
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
        origin: Annotated[str | None, Header(alias="Origin")] = None,
    ) -> InsightResponseModel:
        insights, _ = services()
        actor = principal(authorization, origin)
        try:
            result = insights.answer(
                actor_address=actor.actor_address,
                month=request.month,
                question=request.question,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _insight_response(result)

    return router


def _overview_response(value: InsightsOverview) -> InsightsOverviewModel:
    return InsightsOverviewModel(
        month=value.bundle.month,
        fact_bundle_id=value.bundle.bundle_id,
        insight=_insight_response(value.response),
        notifications=[_notification_response(item) for item in value.notifications],
    )


def _insight_response(value: InsightResponse) -> InsightResponseModel:
    return InsightResponseModel(
        summary=value.summary,
        evidence=[_evidence_response(item) for item in value.evidence],
        caveats=list(value.caveats),
        follow_up_questions=list(value.follow_up_questions),
        mode=value.mode,
        model_id=value.model_id,
        model_revision=value.model_revision,
        refused=value.refused,
    )


def _evidence_response(value: AuthorizedFact) -> EvidenceModel:
    return EvidenceModel(
        fact_id=value.fact_id,
        topic=value.topic,
        statement=value.statement,
        source_kind=value.source_kind,
        source_ids=list(value.source_ids),
        as_of_utc=value.as_of_utc,
    )


def _notification_response(value: InsightNotification) -> InsightNotificationModel:
    return InsightNotificationModel(
        notification_id=value.notification_id,
        severity=value.severity,
        title=value.title,
        message=value.message,
        href=value.href,
        fact_ids=list(value.fact_ids),
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
