from __future__ import annotations

from datetime import datetime

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from server.app.api.problems import register_problem_handlers
from server.app.application.settlement import (
    IdempotencyConflict,
    SettlementRejected,
    SettlementService,
)
from server.app.domain.settlement import SettlementParameters, SignedIntent


class IntentModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    intent_id: str = Field(min_length=1, max_length=128)
    action: str
    actor_public_key: str
    actor_address: str
    resource_id: str = Field(min_length=1, max_length=128)
    parameters_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    nonce: str = Field(min_length=16, max_length=128)
    issued_at: datetime
    expires_at: datetime
    audience: str
    network_id: str
    signature: str


class ParametersModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    credit_units: int = Field(gt=0)
    expected_version: int = Field(ge=0)


class SettlementCommandModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: IntentModel
    parameters: ParametersModel


def create_app(service: SettlementService) -> FastAPI:
    app = FastAPI(title="ResFinance Milestone 0 signed-settlement spike")
    register_problem_handlers(app)

    @app.post("/api/v1/groups/{group_id}/settlements")
    def authorize_settlement(
        group_id: str,
        command: SettlementCommandModel,
        idempotency_key: str = Header(alias="Idempotency-Key"),
        origin: str = Header(alias="Origin"),
    ) -> dict[str, object]:
        if command.intent.resource_id != group_id:
            raise HTTPException(status_code=409, detail="resource mismatch")
        intent = SignedIntent(**command.intent.model_dump())
        parameters = SettlementParameters(**command.parameters.model_dump())
        try:
            return service.authorize(
                intent=intent,
                parameters=parameters,
                idempotency_key=idempotency_key,
                origin=origin,
            ).to_dict()
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except SettlementRejected as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return app
