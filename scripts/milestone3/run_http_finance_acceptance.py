from __future__ import annotations

import argparse
import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from server.app.application.intents import (
    actor_address,
    base58_encode,
    canonical_json,
    parameters_hash,
)

ORIGIN = "https://app.resfinance.local"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Exercise the live Milestone 3 authenticated Finance API."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_id = uuid.uuid4().hex
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    identity = {
        "public_key": base58_encode(public_key),
        "address": actor_address(public_key),
    }
    with httpx.Client(
        base_url=args.base_url,
        headers={"Origin": ORIGIN},
        timeout=30,
    ) as client:
        _wait_for_health(client)
        access_token = _login(client, private_key, identity)
        headers = {"Authorization": f"Bearer {access_token}"}
        income_category = {
            "category_id": f"salary-{run_id[:8]}",
            "name": "Salary",
            "direction": "income",
            "expected_version": 0,
        }
        category_response = _post(
            client,
            "/api/v1/finance/categories",
            headers,
            f"m3-http-{run_id}-category-income",
            income_category,
        )
        duplicate_response = _post(
            client,
            "/api/v1/finance/categories",
            headers,
            f"m3-http-{run_id}-category-income",
            income_category,
        )
        _post(
            client,
            "/api/v1/finance/categories",
            headers,
            f"m3-http-{run_id}-category-expense",
            {
                "category_id": f"groceries-{run_id[:8]}",
                "name": "Groceries",
                "direction": "expense",
                "expected_version": 1,
            },
        )
        _post(
            client,
            "/api/v1/finance/transactions",
            headers,
            f"m3-http-{run_id}-income",
            {
                "transaction_id": f"income-{run_id[:8]}",
                "direction": "income",
                "category_id": f"salary-{run_id[:8]}",
                "amount": {"currency": "USD", "minor_units": 500_000},
                "occurred_on": "2026-10-01",
                "description": "HTTP acceptance salary",
                "recurring_entry_id": None,
                "expected_version": 2,
            },
        )
        _post(
            client,
            "/api/v1/finance/transactions",
            headers,
            f"m3-http-{run_id}-expense",
            {
                "transaction_id": f"expense-{run_id[:8]}",
                "direction": "expense",
                "category_id": f"groceries-{run_id[:8]}",
                "amount": {"currency": "USD", "minor_units": 90_000},
                "occurred_on": "2026-10-10",
                "description": "HTTP acceptance groceries",
                "recurring_entry_id": None,
                "expected_version": 3,
            },
        )
        _post(
            client,
            "/api/v1/finance/budgets",
            headers,
            f"m3-http-{run_id}-budget",
            {
                "budget_id": f"budget-{run_id[:8]}",
                "category_id": f"groceries-{run_id[:8]}",
                "month": "2026-10",
                "limit": {"currency": "USD", "minor_units": 100_000},
                "expected_version": 4,
            },
        )
        _post(
            client,
            "/api/v1/finance/recurring",
            headers,
            f"m3-http-{run_id}-recurring",
            {
                "recurring_entry_id": f"recurring-{run_id[:8]}",
                "direction": "expense",
                "category_id": f"groceries-{run_id[:8]}",
                "amount": {"currency": "USD", "minor_units": 150_000},
                "description": "HTTP acceptance recurring",
                "cadence": "monthly",
                "starts_on": "2026-01-01",
                "ends_on": None,
                "expected_version": 5,
            },
        )
        overview_response = client.get(
            "/api/v1/finance/overview",
            headers=headers,
            params={"month": "2026-10"},
        )
        overview_response.raise_for_status()
        overview = cast(dict[str, Any], overview_response.json())
        summary = cast(dict[str, Any], overview["summary"])
        savings = cast(dict[str, Any], summary["savings"])
        budget_statuses = cast(list[dict[str, Any]], summary["budget_statuses"])
        if (
            cast(dict[str, Any], summary["income"])["minor_units"] != 500_000
            or cast(dict[str, Any], summary["expense"])["minor_units"] != 90_000
            or cast(dict[str, Any], summary["balance"])["minor_units"] != 410_000
            or cast(dict[str, Any], savings["projected"])["minor_units"] != 260_000
            or savings["formula_version"] != "finance-savings-v1"
            or budget_statuses[0]["status"] != "near_limit"
        ):
            raise RuntimeError("live Finance API projection did not reconcile")

        unauthorized = client.get(
            "/api/v1/finance/overview",
            headers={"Authorization": "Bearer invalid"},
            params={"month": "2026-10"},
        )
        if unauthorized.status_code != 401:
            raise RuntimeError("live Finance API accepted an invalid access token")

    print(
        json.dumps(
            {
                "schema_version": 1,
                "completed_at_utc": datetime.now(UTC).isoformat(),
                "category_status": category_response.status_code,
                "duplicate_status": duplicate_response.status_code,
                "duplicate_deduplicated": duplicate_response.json()["deduplicated"],
                "overview_status": overview_response.status_code,
                "projection_version": overview["provenance"]["projection_version"],
                "projected_savings_minor_units": savings["projected"]["minor_units"],
                "budget_status": budget_statuses[0]["status"],
                "invalid_token_status": unauthorized.status_code,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _wait_for_health(client: httpx.Client, timeout_seconds: float = 60.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = client.get("/api/v1/health", timeout=2)
            if response.status_code == 200:
                return
            last_error = RuntimeError(
                f"health endpoint returned HTTP {response.status_code}"
            )
        except httpx.HTTPError as exc:
            last_error = exc
        time.sleep(1)
    raise RuntimeError("API did not become healthy within 60 seconds") from last_error


def _login(
    client: httpx.Client,
    private_key: Ed25519PrivateKey,
    identity: dict[str, str],
) -> str:
    challenge_response = client.post(
        "/api/v1/auth/challenges", json={"wallet": identity}
    )
    challenge_response.raise_for_status()
    challenge = cast(dict[str, Any], challenge_response.json())
    now = datetime.now(UTC)
    parameters = {"challenge": str(challenge["challenge"]), "origin": ORIGIN}
    unsigned = {
        "version": 1,
        "intent_id": f"intent-{uuid.uuid4().hex}",
        "action": "auth.login",
        "actor_public_key": identity["public_key"],
        "actor_address": identity["address"],
        "resource_id": str(challenge["challenge_id"]),
        "parameters_hash": parameters_hash(parameters),
        "nonce": f"nonce-{uuid.uuid4().hex}",
        "issued_at": _timestamp(now),
        "expires_at": _timestamp(now + timedelta(minutes=5)),
        "origin": ORIGIN,
        "audience": "resfinance-api",
        "network_id": "pinned-local-network",
    }
    intent = {
        **unsigned,
        "signature": base58_encode(private_key.sign(canonical_json(unsigned))),
    }
    session_response = client.post(
        "/api/v1/auth/sessions",
        json={"challenge": challenge["challenge"], "intent": intent},
    )
    session_response.raise_for_status()
    return str(session_response.json()["access_token"])


def _post(
    client: httpx.Client,
    path: str,
    headers: dict[str, str],
    idempotency_key: str,
    body: dict[str, object],
) -> httpx.Response:
    response = client.post(
        path,
        headers={**headers, "Idempotency-Key": idempotency_key},
        json=body,
    )
    response.raise_for_status()
    return response


def _timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
