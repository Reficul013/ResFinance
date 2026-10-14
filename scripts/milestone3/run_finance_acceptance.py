from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

from server.app.application.finance import FinanceOverview, FinanceService
from server.app.domain.finance import (
    EntryDirection,
    MonthlyFinanceSummary,
    ObligationDirection,
)
from server.app.infrastructure.encryption import AesGcmCipher
from server.app.infrastructure.event_repository import EncryptedEventRepository
from server.app.infrastructure.resilientdb_cli import DockerResilientDBEventStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Prove the Milestone 3 finance projection survives a full ResilientDB "
            "restart and reproduces exact integer-cent results."
        )
    )
    parser.add_argument("--docker", type=Path, default=Path("docker"))
    parser.add_argument("--docker-host")
    parser.add_argument("--container", default="resfinance-resdb-tools")
    parser.add_argument("--config", default="/config/client.config")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_id = uuid.uuid4().hex
    actor = "0x" + hashlib.sha256(run_id.encode()).hexdigest()[:40]
    store = DockerResilientDBEventStore(
        docker=args.docker,
        docker_host=args.docker_host,
        container=args.container,
        config_path=args.config,
        timeout_seconds=20,
    )
    key = os.urandom(32)
    service = _service(store, key, run_id)

    service.create_category(
        actor_address=actor,
        idempotency_key=f"m3-{run_id}-category-income",
        expected_version=0,
        category_id=f"salary-{run_id[:8]}",
        name="Salary",
        direction=EntryDirection.INCOME,
    )
    duplicate = service.create_category(
        actor_address=actor,
        idempotency_key=f"m3-{run_id}-category-income",
        expected_version=0,
        category_id=f"salary-{run_id[:8]}",
        name="Salary",
        direction=EntryDirection.INCOME,
    )
    service.create_category(
        actor_address=actor,
        idempotency_key=f"m3-{run_id}-category-expense",
        expected_version=1,
        category_id=f"groceries-{run_id[:8]}",
        name="Groceries",
        direction=EntryDirection.EXPENSE,
    )
    service.record_transaction(
        actor_address=actor,
        idempotency_key=f"m3-{run_id}-income",
        expected_version=2,
        transaction_id=f"income-{run_id[:8]}",
        direction=EntryDirection.INCOME,
        category_id=f"salary-{run_id[:8]}",
        amount_minor_units=500_000,
        occurred_on=date(2026, 10, 1),
        description="Milestone 3 salary acceptance",
        recurring_entry_id=None,
    )
    service.record_transaction(
        actor_address=actor,
        idempotency_key=f"m3-{run_id}-expense",
        expected_version=3,
        transaction_id=f"expense-{run_id[:8]}",
        direction=EntryDirection.EXPENSE,
        category_id=f"groceries-{run_id[:8]}",
        amount_minor_units=90_000,
        occurred_on=date(2026, 10, 10),
        description="Milestone 3 groceries acceptance",
        recurring_entry_id=None,
    )
    service.set_budget(
        actor_address=actor,
        idempotency_key=f"m3-{run_id}-budget",
        expected_version=4,
        budget_id=f"budget-{run_id[:8]}",
        category_id=f"groceries-{run_id[:8]}",
        month="2026-10",
        limit_minor_units=100_000,
    )
    service.create_recurring_entry(
        actor_address=actor,
        idempotency_key=f"m3-{run_id}-recurring",
        expected_version=5,
        recurring_entry_id=f"recurring-{run_id[:8]}",
        direction=EntryDirection.EXPENSE,
        category_id=f"groceries-{run_id[:8]}",
        amount_minor_units=150_000,
        description="Milestone 3 recurring acceptance",
        starts_on=date(2026, 1, 1),
        ends_on=None,
    )
    service.record_confirmed_obligation(
        actor_address=actor,
        idempotency_key=f"m3-{run_id}-obligation",
        expected_version=6,
        obligation_id=f"obligation-{run_id[:8]}",
        direction=ObligationDirection.PAYABLE,
        amount_minor_units=20_000,
        due_on=date(2026, 10, 20),
        source_event_id=f"group-event-{run_id[:8]}",
        contract_receipt=f"contract-receipt-{run_id[:8]}",
    )
    service.record_confirmed_obligation(
        actor_address=actor,
        idempotency_key=f"m3-{run_id}-receivable",
        expected_version=7,
        obligation_id=f"receivable-{run_id[:8]}",
        direction=ObligationDirection.RECEIVABLE,
        amount_minor_units=30_000,
        due_on=date(2026, 10, 22),
        source_event_id=f"group-event-receivable-{run_id[:8]}",
        contract_receipt=f"contract-receipt-receivable-{run_id[:8]}",
    )
    before = service.overview(actor_address=actor, month="2026-10")
    _assert_expected(before.summary)

    _restart_stack(args.docker, args.docker_host)
    restarted = _wait_for_projection(
        store=store,
        key=key,
        key_id=run_id,
        actor=actor,
    )
    _assert_expected(restarted.summary)
    evidence = {
        "schema_version": 1,
        "completed_at_utc": datetime.now(UTC).isoformat(),
        "scope": "local development only",
        "projection_version": restarted.summary.projection_version,
        "income_minor_units": restarted.summary.income_minor_units,
        "expense_minor_units": restarted.summary.expense_minor_units,
        "balance_minor_units": restarted.summary.balance_minor_units,
        "actual_savings_minor_units": restarted.summary.actual_savings_minor_units,
        "receivable_minor_units": restarted.summary.receivable_minor_units,
        "payable_minor_units": restarted.summary.payable_minor_units,
        "projected_savings_minor_units": restarted.summary.projected_savings_minor_units,
        "available_savings_minor_units": restarted.summary.available_savings_minor_units,
        "savings_formula_version": restarted.summary.savings_formula_version,
        "budget_status": restarted.summary.budget_statuses[0].status,
        "budget_utilization_basis_points": restarted.summary.budget_statuses[
            0
        ].utilization_basis_points,
        "idempotent_retry": duplicate.deduplicated,
        "replica_restart": True,
        "projection_rebuild_equal": restarted.summary == before.summary,
        "persistent_database": "Apache ResilientDB LevelDB backend",
        "production_or_cloud_readiness": False,
    }
    encoded = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


def _service(
    store: DockerResilientDBEventStore, key: bytes, key_id: str
) -> FinanceService:
    return FinanceService(
        EncryptedEventRepository(
            store,
            AesGcmCipher(key, key_id=f"m3-ephemeral-{key_id}"),
        )
    )


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


def _wait_for_projection(
    *,
    store: DockerResilientDBEventStore,
    key: bytes,
    key_id: str,
    actor: str,
) -> FinanceOverview:
    deadline = time.monotonic() + 60
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            overview = _service(store, key, key_id).overview(
                actor_address=actor, month="2026-10"
            )
            if overview.summary.projection_version == 8:
                return overview
        except (RuntimeError, subprocess.SubprocessError, ValueError) as exc:
            last_error = exc
        time.sleep(1)
    raise RuntimeError("finance projection did not recover after restart") from last_error


def _assert_expected(summary: MonthlyFinanceSummary) -> None:
    expected = {
        "projection_version": 8,
        "income_minor_units": 500_000,
        "expense_minor_units": 90_000,
        "balance_minor_units": 410_000,
        "actual_savings_minor_units": 410_000,
        "receivable_minor_units": 30_000,
        "payable_minor_units": 20_000,
        "projected_savings_minor_units": 270_000,
        "available_savings_minor_units": 270_000,
    }
    for name, value in expected.items():
        if getattr(summary, name) != value:
            raise RuntimeError(f"unexpected {name}: {getattr(summary, name)}")
    budget_statuses = summary.budget_statuses
    if (
        len(budget_statuses) != 1
        or budget_statuses[0].status != "near_limit"
        or budget_statuses[0].utilization_basis_points != 9_000
    ):
        raise RuntimeError("budget alert did not rebuild exactly")


if __name__ == "__main__":
    raise SystemExit(main())
