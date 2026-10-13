from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from server.app.api.problems import register_problem_handlers
from server.app.main import create_app


def test_health_endpoint_is_versioned() -> None:
    response = TestClient(create_app()).get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "resfinance-api"}


def test_http_errors_use_problem_details_without_echoing_request_data() -> None:
    app = FastAPI()
    register_problem_handlers(app)

    @app.get("/failure")
    def failure(secret: str) -> None:
        del secret
        raise HTTPException(status_code=409, detail="resource conflict")

    response = TestClient(app).get(
        "/failure?secret=never-echo-this", headers={"X-Request-Id": "trace-001"}
    )

    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json() == {
        "type": "https://resfinance.local/problems/http-409",
        "title": "Conflict",
        "status": 409,
        "detail": "resource conflict",
        "instance": "/failure",
        "trace_id": "trace-001",
    }
    assert "never-echo-this" not in response.text
