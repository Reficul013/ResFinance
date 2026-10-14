from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI

from server.app.api.auth import create_auth_router
from server.app.api.health import router as health_router
from server.app.api.problems import register_problem_handlers
from server.app.application.authentication import AuthenticationService
from server.app.infrastructure.auth_repository import AuthRepository
from server.app.infrastructure.resilientdb_cli import ResilientDBCliStore


def create_app(
    auth_service: AuthenticationService | None = None,
    *,
    secure_cookie: bool = False,
) -> FastAPI:
    app = FastAPI(
        title="ResFinance API",
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    register_problem_handlers(app)
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(
        create_auth_router(auth_service, secure_cookie=secure_cookie),
        prefix="/api/v1",
    )
    return app


def _authentication_from_environment() -> AuthenticationService | None:
    tool = os.environ.get("RESFINANCE_RESDB_TOOL")
    config = os.environ.get("RESFINANCE_RESDB_CONFIG")
    if not tool or not config:
        return None
    store = ResilientDBCliStore(tool=Path(tool), config_path=Path(config))
    return AuthenticationService(AuthRepository(store))


app = create_app(
    _authentication_from_environment(),
    secure_cookie=os.environ.get("RESFINANCE_SECURE_COOKIE", "false").lower()
    == "true",
)
