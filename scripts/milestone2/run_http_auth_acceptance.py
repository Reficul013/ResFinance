from __future__ import annotations

import argparse
import json
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
        description="Exercise the live Milestone 2 FastAPI authentication boundary."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
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
        session = cast(dict[str, Any], session_response.json())
        first_refresh = client.cookies.get("resfinance_refresh")
        if first_refresh is None:
            raise RuntimeError("live API did not set the refresh cookie")

        refresh_response = client.post("/api/v1/auth/refresh")
        refresh_response.raise_for_status()
        refreshed = cast(dict[str, Any], refresh_response.json())
        second_refresh = client.cookies.get("resfinance_refresh")
        if second_refresh is None or second_refresh == first_refresh:
            raise RuntimeError("live API did not rotate the refresh cookie")

        with httpx.Client(
            base_url=args.base_url,
            headers={"Origin": ORIGIN},
            cookies={"resfinance_refresh": first_refresh},
            timeout=30,
        ) as replay_client:
            if replay_client.post("/api/v1/auth/refresh").status_code != 401:
                raise RuntimeError("live API accepted a rotated refresh token")

        logout_response = client.delete(
            "/api/v1/auth/sessions/current",
            headers={"Authorization": f"Bearer {refreshed['access_token']}"},
        )
        if logout_response.status_code != 204:
            raise RuntimeError("live API logout failed")
        client.cookies.set("resfinance_refresh", second_refresh)
        if client.post("/api/v1/auth/refresh").status_code != 401:
            raise RuntimeError("live API accepted a logged-out refresh session")

        wrong_origin = client.post(
            "/api/v1/auth/challenges",
            headers={"Origin": "https://evil.example"},
            json={"wallet": identity},
        )
        if wrong_origin.status_code != 403:
            raise RuntimeError("live API accepted a wrong-origin challenge request")

    print(
        json.dumps(
            {
                "schema_version": 1,
                "completed_at_utc": datetime.now(UTC).isoformat(),
                "challenge_status": challenge_response.status_code,
                "session_status": session_response.status_code,
                "refresh_status": refresh_response.status_code,
                "logout_status": logout_response.status_code,
                "rotated_refresh_replay_status": 401,
                "wrong_origin_status": wrong_origin.status_code,
                "actor_address_matches": session["actor_address"]
                == identity["address"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
