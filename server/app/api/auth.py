from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, NoReturn

from fastapi import APIRouter, Cookie, Header, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field

from server.app.application.authentication import (
    AuthenticationService,
    AuthRejected,
    OriginRejected,
    ReplayRejected,
    SessionUnauthorized,
)
from server.app.domain.auth import SessionGrant, WalletIdentity
from server.app.domain.settlement import SignedIntent

REFRESH_COOKIE = "resfinance_refresh"


class WalletIdentityModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    public_key: str = Field(min_length=32, max_length=128)
    address: str = Field(pattern=r"^0x[0-9a-f]{40}$")


class ChallengeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    wallet: WalletIdentityModel


class ChallengeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    challenge_id: str
    challenge: str
    expires_at: datetime
    audience: str
    network_id: str


class SignedIntentModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1]
    intent_id: str = Field(min_length=1, max_length=128)
    action: str = Field(min_length=1, max_length=128)
    actor_public_key: str = Field(min_length=32, max_length=128)
    actor_address: str = Field(pattern=r"^0x[0-9a-f]{40}$")
    resource_id: str = Field(min_length=1, max_length=160)
    parameters_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    nonce: str = Field(min_length=16, max_length=128)
    issued_at: datetime
    expires_at: datetime
    origin: str = Field(min_length=1, max_length=256)
    audience: str = Field(min_length=1, max_length=128)
    network_id: str = Field(min_length=1, max_length=128)
    signature: str = Field(min_length=32, max_length=192)


class SessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    challenge: str = Field(min_length=32, max_length=256)
    intent: SignedIntentModel


class SessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    access_token: str
    token_type: Literal["Bearer"] = "Bearer"
    expires_at: datetime
    actor_address: str


def create_auth_router(
    service: AuthenticationService | None,
    *,
    secure_cookie: bool,
) -> APIRouter:
    router = APIRouter(prefix="/auth", tags=["authentication"])

    def auth_service() -> AuthenticationService:
        if service is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="authentication persistence is not configured",
            )
        return service

    @router.post("/challenges", response_model=ChallengeResponse, status_code=201)
    def create_challenge(
        request: ChallengeRequest,
        origin: Annotated[str, Header(alias="Origin")],
    ) -> ChallengeResponse:
        try:
            challenge = auth_service().create_challenge(
                identity=WalletIdentity(
                    public_key=request.wallet.public_key,
                    address=request.wallet.address,
                ),
                origin=origin,
            )
        except AuthRejected as exc:
            _raise_auth_error(exc)
        return ChallengeResponse(
            challenge_id=challenge.challenge_id,
            challenge=challenge.challenge,
            expires_at=challenge.expires_at,
            audience=challenge.audience,
            network_id=challenge.network_id,
        )

    @router.post("/sessions", response_model=SessionResponse, status_code=201)
    def create_session(
        request: SessionRequest,
        response: Response,
        origin: Annotated[str, Header(alias="Origin")],
    ) -> SessionResponse:
        try:
            grant = auth_service().create_session(
                intent=SignedIntent(**request.intent.model_dump()),
                challenge=request.challenge,
                origin=origin,
            )
        except AuthRejected as exc:
            _raise_auth_error(exc)
        _set_refresh_cookie(
            response,
            grant.refresh_token,
            grant.refresh_expires_at,
            secure_cookie=secure_cookie,
        )
        return _session_response(grant)

    @router.post("/refresh", response_model=SessionResponse)
    def refresh_session(
        response: Response,
        origin: Annotated[str, Header(alias="Origin")],
        refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
    ) -> SessionResponse:
        if refresh_token is None:
            raise HTTPException(status_code=401, detail="refresh cookie is required")
        try:
            grant = auth_service().refresh_session(
                refresh_token=refresh_token, origin=origin
            )
        except AuthRejected as exc:
            _raise_auth_error(exc)
        _set_refresh_cookie(
            response,
            grant.refresh_token,
            grant.refresh_expires_at,
            secure_cookie=secure_cookie,
        )
        return _session_response(grant)

    @router.delete("/sessions/current", status_code=204)
    def logout(
        response: Response,
        origin: Annotated[str, Header(alias="Origin")],
        authorization: Annotated[str, Header(alias="Authorization")],
        refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
    ) -> None:
        prefix = "Bearer "
        if not authorization.startswith(prefix) or len(authorization) <= len(prefix):
            raise HTTPException(status_code=401, detail="bearer token is required")
        try:
            auth_service().logout(
                access_token=authorization[len(prefix) :],
                refresh_token=refresh_token,
                origin=origin,
            )
        except AuthRejected as exc:
            _raise_auth_error(exc)
        response.delete_cookie(
            REFRESH_COOKIE,
            path="/api/v1/auth",
            secure=secure_cookie,
            httponly=True,
            samesite="strict",
        )

    return router


def _session_response(grant: SessionGrant) -> SessionResponse:
    return SessionResponse(
        access_token=grant.access_token,
        expires_at=grant.access_expires_at,
        actor_address=grant.actor_address,
    )


def _set_refresh_cookie(
    response: Response,
    token: str,
    expires_at: datetime,
    *,
    secure_cookie: bool,
) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        expires=expires_at,
        path="/api/v1/auth",
        secure=secure_cookie,
        httponly=True,
        samesite="strict",
    )


def _raise_auth_error(exc: AuthRejected) -> NoReturn:
    if isinstance(exc, OriginRejected):
        status_code = 403
    elif isinstance(exc, SessionUnauthorized):
        status_code = 401
    elif isinstance(exc, ReplayRejected):
        status_code = 409
    else:
        status_code = 422
    raise HTTPException(status_code=status_code, detail=str(exc)) from exc
