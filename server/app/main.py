from __future__ import annotations

from fastapi import FastAPI

from server.app.api.health import router as health_router
from server.app.api.problems import register_problem_handlers


def create_app() -> FastAPI:
    app = FastAPI(
        title="ResFinance API",
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    register_problem_handlers(app)
    app.include_router(health_router, prefix="/api/v1")
    return app


app = create_app()
