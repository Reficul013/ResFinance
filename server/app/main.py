from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI

from blockchain.adapter.resfinance_settlement import LocalResContractCliGateway
from server.app.api.auth import create_auth_router
from server.app.api.finance import create_finance_router
from server.app.api.groups import create_groups_router
from server.app.api.health import router as health_router
from server.app.api.portfolio import create_portfolio_router
from server.app.api.problems import register_problem_handlers
from server.app.application.authentication import AuthenticationService
from server.app.application.finance import FinanceService
from server.app.application.groups import GroupService
from server.app.application.portfolio import PortfolioService
from server.app.infrastructure.auth_repository import AuthRepository
from server.app.infrastructure.blob_repository import EncryptedBlobRepository
from server.app.infrastructure.encryption import AesGcmCipher
from server.app.infrastructure.event_repository import EncryptedEventRepository
from server.app.infrastructure.portfolio_repository import PortfolioResearchRepository
from server.app.infrastructure.research_repository import ResearchRunRepository
from server.app.infrastructure.resilientdb_cli import ResilientDBCliStore


def create_app(
    auth_service: AuthenticationService | None = None,
    finance_service: FinanceService | None = None,
    group_service: GroupService | None = None,
    portfolio_service: PortfolioService | None = None,
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
    app.include_router(
        create_groups_router(group_service, auth_service),
        prefix="/api/v1",
    )
    app.include_router(
        create_portfolio_router(portfolio_service, auth_service),
        prefix="/api/v1",
    )
    return app


def _services_from_environment() -> tuple[
    AuthenticationService | None,
    FinanceService | None,
    GroupService | None,
    PortfolioService | None,
]:
    tool = os.environ.get("RESFINANCE_RESDB_TOOL")
    config = os.environ.get("RESFINANCE_RESDB_CONFIG")
    if not tool or not config:
        return None, None, None, None
    store = ResilientDBCliStore(tool=Path(tool), config_path=Path(config))
    authentication = AuthenticationService(AuthRepository(store))
    event_key_path = os.environ.get("RESFINANCE_EVENT_KEY_FILE")
    if not event_key_path:
        return authentication, None, None, None
    key = Path(event_key_path).read_bytes()
    repository = EncryptedEventRepository(
        store,
        AesGcmCipher(key, key_id="local-finance-event-key-v1"),
    )
    finance = FinanceService(repository)
    contract_tool = os.environ.get("RESFINANCE_RESCONTRACT_TOOL")
    contract_config = os.environ.get("RESFINANCE_RESCONTRACT_CONFIG")
    contract_address = os.environ.get("RESFINANCE_RESCONTRACT_ADDRESS")
    gateway_caller = os.environ.get("RESFINANCE_RESCONTRACT_CALLER")
    registry_path = os.environ.get("RESFINANCE_RESCONTRACT_REGISTRY")
    if registry_path and (not contract_address or not gateway_caller):
        registry = json.loads(Path(registry_path).read_text(encoding="utf-8"))
        contract_address = str(registry.get("contract_address", ""))
        gateway_caller = str(registry.get("gateway_caller", ""))
    if not all((contract_tool, contract_config, contract_address, gateway_caller)):
        blobs = EncryptedBlobRepository(
            store, AesGcmCipher(key, key_id="local-research-blob-key-v1")
        )
        research = ResearchRunRepository(store, blobs)
        portfolio = PortfolioService(
            repository,
            PortfolioResearchRepository(store, research),
            finance,
        )
        return authentication, finance, None, portfolio
    contract = LocalResContractCliGateway(
        tool=Path(str(contract_tool)),
        config_path=Path(str(contract_config)),
        contract_address=str(contract_address),
        gateway_caller=str(gateway_caller),
    )
    blobs = EncryptedBlobRepository(store, AesGcmCipher(key, key_id="local-research-blob-key-v1"))
    research = ResearchRunRepository(store, blobs)
    portfolio = PortfolioService(repository, PortfolioResearchRepository(store, research), finance)
    return authentication, finance, GroupService(repository, contract, finance), portfolio


_authentication, _finance, _groups, _portfolio = _services_from_environment()
app = create_app(
    _authentication,
    _finance,
    _groups,
    _portfolio,
    secure_cookie=os.environ.get("RESFINANCE_SECURE_COOKIE", "false").lower() == "true",
)
