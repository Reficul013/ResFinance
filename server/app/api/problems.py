from __future__ import annotations

import secrets
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

PROBLEM_BASE = "https://resfinance.local/problems"


def _trace_id(request: Request) -> str:
    candidate = request.headers.get("X-Request-Id", "")
    if candidate and len(candidate) <= 128 and candidate.isascii():
        return candidate
    return secrets.token_hex(16)


def problem_response(
    request: Request,
    *,
    status: int,
    problem_type: str,
    title: str,
    detail: str,
    extensions: dict[str, Any] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"{PROBLEM_BASE}/{problem_type}",
        "title": title,
        "status": status,
        "detail": detail,
        "instance": request.url.path,
        "trace_id": _trace_id(request),
    }
    if extensions:
        body.update(extensions)
    return JSONResponse(
        status_code=status,
        content=body,
        media_type="application/problem+json",
    )


def register_problem_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_problem(request: Request, exc: HTTPException) -> JSONResponse:
        title = {
            400: "Bad request",
            401: "Unauthorized",
            403: "Forbidden",
            404: "Not found",
            409: "Conflict",
            422: "Unprocessable content",
            503: "Service unavailable",
        }.get(exc.status_code, "Request failed")
        detail = exc.detail if isinstance(exc.detail, str) else title
        return problem_response(
            request,
            status=exc.status_code,
            problem_type=f"http-{exc.status_code}",
            title=title,
            detail=detail,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_problem(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = [
            {
                "field": ".".join(str(part) for part in error["loc"]),
                "code": str(error["type"]),
            }
            for error in exc.errors()
        ]
        return problem_response(
            request,
            status=422,
            problem_type="validation-error",
            title="Validation failed",
            detail="The request did not satisfy the API contract.",
            extensions={"errors": errors},
        )
