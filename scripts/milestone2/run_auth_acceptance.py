from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from server.app.application.authentication import (
    AuthenticationService,
    ReplayRejected,
    SessionUnauthorized,
)
from server.app.application.intents import (
    actor_address,
    base58_encode,
    canonical_json,
    parameters_hash,
)
from server.app.domain.auth import SessionGrant, WalletIdentity
from server.app.domain.settlement import SignedIntent
from server.app.infrastructure.auth_repository import AuthRepository
from server.app.infrastructure.resilientdb_cli import DockerResilientDBEventStore

ORIGIN = "https://app.resfinance.local"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Prove challenge authentication, refresh persistence, rotation, replay "
            "rejection, and logout against the Milestone 1 ResilientDB stack."
        )
    )
    parser.add_argument("--docker", type=Path, default=Path("docker"))
    parser.add_argument("--docker-host")
    parser.add_argument("--container", default="resfinance-resdb-tools")
    parser.add_argument("--config", default="/config/client.config")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    store = DockerResilientDBEventStore(
        docker=args.docker,
        docker_host=args.docker_host,
        container=args.container,
        config_path=args.config,
        timeout_seconds=15,
    )
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    identity = WalletIdentity(
        public_key=base58_encode(public_key),
        address=actor_address(public_key),
    )
    service = AuthenticationService(AuthRepository(store))
    challenge = service.create_challenge(identity=identity, origin=ORIGIN)
    now = datetime.now(UTC)
    parameter_values = {"challenge": challenge.challenge, "origin": ORIGIN}
    intent_id = f"intent-{uuid.uuid4().hex}"
    nonce = f"nonce-{uuid.uuid4().hex}"
    expires_at = now + timedelta(minutes=5)
    signature_payload = {
        "version": 1,
        "intent_id": intent_id,
        "action": "auth.login",
        "actor_public_key": identity.public_key,
        "actor_address": identity.address,
        "resource_id": challenge.challenge_id,
        "parameters_hash": parameters_hash(parameter_values),
        "nonce": nonce,
        "issued_at": _timestamp(now),
        "expires_at": _timestamp(expires_at),
        "origin": ORIGIN,
        "audience": "resfinance-api",
        "network_id": "pinned-local-network",
    }
    intent = SignedIntent(
        version=1,
        intent_id=intent_id,
        action="auth.login",
        actor_public_key=identity.public_key,
        actor_address=identity.address,
        resource_id=challenge.challenge_id,
        parameters_hash=parameters_hash(parameter_values),
        nonce=nonce,
        issued_at=now,
        expires_at=expires_at,
        origin=ORIGIN,
        audience="resfinance-api",
        network_id="pinned-local-network",
        signature=base58_encode(private_key.sign(canonical_json(signature_payload))),
    )
    grant = service.create_session(
        intent=intent,
        challenge=challenge.challenge,
        origin=ORIGIN,
    )

    _restart_stack(args.docker, args.docker_host)
    restarted = AuthenticationService(AuthRepository(store))
    refreshed = _wait_for_refresh(restarted, grant.refresh_token)

    old_refresh_rejected = False
    try:
        restarted.refresh_session(refresh_token=grant.refresh_token, origin=ORIGIN)
    except SessionUnauthorized:
        old_refresh_rejected = True
    if not old_refresh_rejected:
        raise RuntimeError("rotated refresh token was accepted")

    replay_rejected = False
    try:
        restarted.create_session(
            intent=intent,
            challenge=challenge.challenge,
            origin=ORIGIN,
        )
    except ReplayRejected:
        replay_rejected = True
    if not replay_rejected:
        raise RuntimeError("used authentication challenge was accepted")

    restarted.logout(
        access_token=refreshed.access_token,
        refresh_token=refreshed.refresh_token,
        origin=ORIGIN,
    )
    logout_rejected = False
    try:
        restarted.refresh_session(
            refresh_token=refreshed.refresh_token, origin=ORIGIN
        )
    except SessionUnauthorized:
        logout_rejected = True
    if not logout_rejected:
        raise RuntimeError("logged-out refresh session was accepted")

    records = "".join(store.range_values("auth:"))
    for prohibited in (
        challenge.challenge,
        grant.access_token,
        grant.refresh_token,
        refreshed.access_token,
        refreshed.refresh_token,
    ):
        if prohibited in records:
            raise RuntimeError("raw challenge or token was persisted")
    if hashlib.sha256(grant.refresh_token.encode()).hexdigest() not in records:
        raise RuntimeError("refresh-session hash was not persisted")

    print(
        json.dumps(
            {
                "schema_version": 1,
                "completed_at_utc": datetime.now(UTC).isoformat(),
                "approved_challenge_authenticated": True,
                "refresh_survived_replica_restart": True,
                "refresh_rotation_rejected_replay": old_refresh_rejected,
                "challenge_replay_rejected": replay_rejected,
                "logout_revoked_session": logout_rejected,
                "raw_tokens_or_challenges_persisted": False,
                "persistent_database": "Apache ResilientDB LevelDB backend",
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _wait_for_refresh(
    service: AuthenticationService, refresh_token: str
) -> SessionGrant:
    deadline = time.monotonic() + 60
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return service.refresh_session(refresh_token=refresh_token, origin=ORIGIN)
        except (SessionUnauthorized, RuntimeError, subprocess.SubprocessError) as exc:
            last_error = exc
            time.sleep(1)
    raise RuntimeError("refresh session was not readable after restart") from last_error


def _restart_stack(docker: Path, docker_host: str | None) -> None:
    command = [str(docker)]
    if docker_host:
        command.extend(["--host", docker_host])
    command.extend(
        [
            "compose",
            "restart",
            "resdb-1",
            "resdb-2",
            "resdb-3",
            "resdb-4",
            "resdb-proxy",
        ]
    )
    subprocess.run(command, check=True, timeout=180)


def _timestamp(value: object) -> str:
    if not isinstance(value, datetime):
        raise TypeError("timestamp value is invalid")
    return value.isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
