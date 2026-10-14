from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI

from server.app.api.auth import create_auth_router
from server.app.api.finance import create_finance_router
from server.app.api.health import router as health_router
from server.app.api.problems import register_problem_handlers
from server.app.application.authentication import AuthenticationService
from server.app.application.finance import FinanceService
from server.app.infrastructure.auth_repository import AuthRepository
from server.app.infrastructure.encryption import AesGcmCipher
from server.app.infrastructure.event_repository import EncryptedEventRepository
from server.app.infrastructure.resilientdb_cli import ResilientDBCliStore


def create_app(
    auth_service: AuthenticationService | None = None,
    finance_service: FinanceService | None = None,
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
    app.include_router(
        create_finance_router(finance_service, auth_service),
        prefix="/api/v1",
    )
    return app


def _services_from_environment() -> tuple[
    AuthenticationService | None, FinanceService | None
]:
    tool = os.environ.get("RESFINANCE_RESDB_TOOL")
    config = os.environ.get("RESFINANCE_RESDB_CONFIG")
    if not tool or not config:
        return None, None
    store = ResilientDBCliStore(tool=Path(tool), config_path=Path(config))
    authentication = AuthenticationService(AuthRepository(store))
    event_key_path = os.environ.get("RESFINANCE_EVENT_KEY_FILE")
    if not event_key_path:
        return authentication, None
    key = Path(event_key_path).read_bytes()
    finance = FinanceService(
        EncryptedEventRepository(
            store,
            AesGcmCipher(key, key_id="local-finance-event-key-v1"),
        )
    )
    return authentication, finance


_authentication, _finance = _services_from_environment()
app = create_app(
    _authentication,
    _finance,
    secure_cookie=os.environ.get("RESFINANCE_SECURE_COOKIE", "false").lower()
    == "true",
)
