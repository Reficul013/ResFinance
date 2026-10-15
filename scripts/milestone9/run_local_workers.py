from __future__ import annotations

import argparse
import json
import subprocess
import uuid
from datetime import UTC, datetime, time
from pathlib import Path
from typing import cast

from scripts.milestone9.local_handoff import ROOT
from server.app.application.crypto_ingestion import CryptoIngestionService
from server.app.application.ports import KeyValueStore
from server.app.domain.crypto import CryptoAsset
from server.app.infrastructure.crypto_repository import CryptoResearchRepository
from server.app.infrastructure.provider_adapters import (
    CoinGeckoCurrentQuoteAdapter,
    CoinMetricsMarketAdapter,
)
from server.app.infrastructure.resilientdb_cli import DockerResilientDBEventStore
from server.app.workers.crypto_ingestion import IngestionJob, run_ingestion_job

JOB_PREFIX = "job:local:"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run and inspect explicit local jobs")
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest-current")
    add_store_arguments(ingest)
    reconcile = commands.add_parser("reconcile")
    add_store_arguments(reconcile)
    reconcile.add_argument("--group-id", required=True)
    status = commands.add_parser("status")
    add_store_arguments(status)
    return parser.parse_args()


def add_store_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--docker", type=Path, default=Path("docker"))
    parser.add_argument("--docker-host")
    parser.add_argument("--container", default="resfinance-resdb-tools")


def main() -> int:
    args = parse_args()
    store = event_store(args)
    if args.command == "status":
        return show_status(store)
    job_id = f"{args.command}-{uuid.uuid4().hex}"
    started = datetime.now(UTC)
    write_status(store, job_id, "running", started, None, {})
    try:
        details = (
            ingest_current(store, job_id)
            if args.command == "ingest-current"
            else reconcile(args)
        )
    except Exception as exc:
        write_status(
            store,
            job_id,
            "failed",
            started,
            datetime.now(UTC),
            {"error": str(exc)},
        )
        raise
    write_status(store, job_id, "completed", started, datetime.now(UTC), details)
    print(json.dumps({"job_id": job_id, "status": "completed", **details}, indent=2))
    return 0


def event_store(args: argparse.Namespace) -> DockerResilientDBEventStore:
    return DockerResilientDBEventStore(
        docker=args.docker,
        docker_host=args.docker_host,
        container=args.container,
        config_path="/config/client.config",
        timeout_seconds=60,
    )


def ingest_current(store: KeyValueStore, job_id: str) -> dict[str, object]:
    now = datetime.now(UTC)
    day_start = datetime.combine(now.date(), time.min, tzinfo=UTC)
    day_end = datetime.combine(now.date(), time.max, tzinfo=UTC)
    repository = CryptoResearchRepository(store)
    receipts = run_ingestion_job(
        CryptoIngestionService(repository),
        IngestionJob(
            job_id=job_id,
            assets=tuple(CryptoAsset),
            start_utc=day_start,
            end_utc=day_end,
        ),
        (CoinMetricsMarketAdapter(), CoinGeckoCurrentQuoteAdapter()),
    )
    return {
        "kind": "manual-current-market-ingestion",
        "continuous": False,
        "providers": [receipt.provider for receipt in receipts],
        "inserted_count": sum(receipt.inserted_count for receipt in receipts),
        "deduplicated_count": sum(receipt.deduplicated_count for receipt in receipts),
    }


def reconcile(args: argparse.Namespace) -> dict[str, object]:
    completed = subprocess.run(
        [
            "docker",
            "compose",
            "--profile",
            "app",
            "exec",
            "-T",
            "api",
            "python",
            "-m",
            "server.app.workers.reconciliation",
            "--group-id",
            args.group_id,
        ],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    result = json.loads(completed.stdout)
    if not isinstance(result, dict):
        raise RuntimeError("reconciliation worker returned an invalid status")
    return {"kind": "manual-group-reconciliation", "continuous": False, **result}


def write_status(
    store: KeyValueStore,
    job_id: str,
    status: str,
    started: datetime,
    completed: datetime | None,
    details: dict[str, object],
) -> None:
    value = {
        "schema_version": 1,
        "job_id": job_id,
        "status": status,
        "started_at_utc": started.isoformat().replace("+00:00", "Z"),
        "completed_at_utc": (
            completed.isoformat().replace("+00:00", "Z") if completed else None
        ),
        "details": details,
    }
    sequence = "000-running" if status == "running" else "100-terminal"
    store.put(
        f"{JOB_PREFIX}{job_id}:{sequence}",
        json.dumps(value, separators=(",", ":"), sort_keys=True),
    )


def show_status(store: KeyValueStore) -> int:
    jobs = [
        cast(dict[str, object], json.loads(value))
        for value in store.range_values(JOB_PREFIX)
    ]
    print(json.dumps(jobs, indent=2, sort_keys=True))
    return 1 if any(job.get("status") == "failed" for job in jobs) else 0


if __name__ == "__main__":
    raise SystemExit(main())
