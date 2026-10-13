from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from server.app.application.projections import rebuild_projection
from server.app.domain.events import AppendEventCommand, DomainEvent
from server.app.infrastructure.encryption import AesGcmCipher
from server.app.infrastructure.event_repository import (
    CorruptEventError,
    EncryptedEventRepository,
)
from server.app.infrastructure.resilientdb_cli import DockerResilientDBEventStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Prove encrypted event write, restart, read, rebuild, and deduplication "
            "against the Milestone 1 ResilientDB Compose stack."
        )
    )
    parser.add_argument("--docker", type=Path, default=Path("docker"))
    parser.add_argument("--docker-host")
    parser.add_argument("--container", default="resfinance-resdb-tools")
    parser.add_argument("--config", default="/config/client.config")
    return parser.parse_args()


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


def _wait_for_read(
    repository: EncryptedEventRepository,
    *,
    store: DockerResilientDBEventStore,
    command: AppendEventCommand,
    expected_event_id: str,
    tenant_id: str,
    aggregate_id: str,
) -> list[DomainEvent]:
    deadline = time.monotonic() + 60
    last_error: Exception | None = None
    idempotency_hash = hashlib.sha256(command.idempotency_key.encode()).hexdigest()
    command_key = f"cmd:{command.tenant_id}:{command.command_type}:{idempotency_hash}"
    while time.monotonic() < deadline:
        try:
            stream = list(
                repository.load_stream(
                    tenant_id=tenant_id,
                    aggregate_type="finance-account",
                    aggregate_id=aggregate_id,
                )
            )
            command_record = store.get(command_key)
            if (
                command_record is not None
                and len(stream) == 1
                and stream[0].event_id == expected_event_id
            ):
                return stream
        except (CorruptEventError, RuntimeError, subprocess.SubprocessError) as exc:
            last_error = exc
        time.sleep(1)
    raise RuntimeError("ResilientDB did not become readable after restart") from last_error


def main() -> int:
    args = parse_args()
    run_id = uuid.uuid4().hex
    tenant_id = f"tenant-m1-{run_id[:12]}"
    aggregate_id = f"account-m1-{run_id[:12]}"
    store = DockerResilientDBEventStore(
        docker=args.docker,
        docker_host=args.docker_host,
        container=args.container,
        config_path=args.config,
        timeout_seconds=15,
    )
    key = os.urandom(32)
    cipher = AesGcmCipher(key, key_id=f"m1-ephemeral-{run_id}")
    repository = EncryptedEventRepository(store, cipher)
    command = AppendEventCommand(
        tenant_id=tenant_id,
        actor_id=f"wallet-{run_id[:12]}",
        command_type="finance.record-income",
        idempotency_key=f"idempotency-{run_id}",
        event_type="finance.income-recorded",
        aggregate_type="finance-account",
        aggregate_id=aggregate_id,
        expected_version=0,
        payload={"currency": "USD", "minor_units": 12500, "memo": "m1-acceptance"},
        source_references=(f"acceptance-{run_id}",),
    )

    first = repository.append(command)
    before_restart = repository.append(command)
    if not before_restart.deduplicated:
        raise RuntimeError("pre-restart idempotency check failed")

    _restart_stack(args.docker, args.docker_host)
    restarted_repository = EncryptedEventRepository(store, cipher)
    stream = _wait_for_read(
        restarted_repository,
        store=store,
        command=command,
        expected_event_id=first.event.event_id,
        tenant_id=tenant_id,
        aggregate_id=aggregate_id,
    )
    after_restart = restarted_repository.append(command)
    if not after_restart.deduplicated or after_restart.event.event_id != first.event.event_id:
        raise RuntimeError("post-restart idempotency check failed")
    balance = rebuild_projection(
        stream,
        initial=0,
        reducer=lambda total, event: total + int(event.payload["minor_units"]),
    )
    if balance != 12500:
        raise RuntimeError("projection rebuild did not reproduce the expected balance")

    print(
        json.dumps(
            {
                "schema_version": 1,
                "completed_at_utc": datetime.now(UTC).isoformat(),
                "event_id": first.event.event_id,
                "encrypted_at_rest": True,
                "replica_restart": True,
                "read_after_restart": len(stream) == 1,
                "projection_balance_minor_units": balance,
                "deduplicated_before_restart": before_restart.deduplicated,
                "deduplicated_after_restart": after_restart.deduplicated,
                "persistent_database": "Apache ResilientDB LevelDB backend",
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
