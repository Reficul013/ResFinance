from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import sys
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from blockchain.adapter.resfinance_settlement import (  # noqa: E402
    DockerResContractCliGateway,
)
from server.app.application.finance import FinanceService  # noqa: E402
from server.app.application.groups import (  # noqa: E402
    GroupRejected,
    GroupService,
    InjectedSagaCrash,
)
from server.app.application.intents import (  # noqa: E402
    actor_address,
    base58_encode,
    canonical_json,
    parameters_hash,
)
from server.app.domain.groups import ObligationStatus  # noqa: E402
from server.app.domain.settlement import SignedIntent  # noqa: E402
from server.app.infrastructure.encryption import AesGcmCipher  # noqa: E402
from server.app.infrastructure.event_repository import (  # noqa: E402
    EncryptedEventRepository,
)
from server.app.infrastructure.resilientdb_cli import (  # noqa: E402
    DockerResilientDBEventStore,
)

ORIGIN = "https://app.resfinance.local"


def _wallet() -> tuple[Ed25519PrivateKey, dict[str, str]]:
    private_key = Ed25519PrivateKey.generate()
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return private_key, {
        "public_key": base58_encode(public_bytes),
        "address": actor_address(public_bytes),
    }


def _intent(
    private_key: Ed25519PrivateKey,
    identity: Mapping[str, str],
    *,
    action: str,
    resource_id: str,
    parameters: Mapping[str, object],
    now: datetime,
) -> SignedIntent:
    nonce = secrets.token_hex(16)
    payload: dict[str, object] = {
        "version": 1,
        "intent_id": f"intent-{uuid.uuid4().hex}",
        "action": action,
        "actor_public_key": identity["public_key"],
        "actor_address": identity["address"],
        "resource_id": resource_id,
        "parameters_hash": parameters_hash(parameters),
        "nonce": nonce,
        "issued_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": (now + timedelta(minutes=5))
        .isoformat()
        .replace("+00:00", "Z"),
        "origin": ORIGIN,
        "audience": "resfinance-api",
        "network_id": "pinned-local-network",
    }
    payload["signature"] = base58_encode(private_key.sign(canonical_json(payload)))
    return SignedIntent(
        version=1,
        intent_id=str(payload["intent_id"]),
        action=action,
        actor_public_key=identity["public_key"],
        actor_address=identity["address"],
        resource_id=resource_id,
        parameters_hash=str(payload["parameters_hash"]),
        nonce=nonce,
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
        origin=ORIGIN,
        audience="resfinance-api",
        network_id="pinned-local-network",
        signature=str(payload["signature"]),
    )


def _registry(docker: Path, container: str) -> dict[str, object]:
    completed = subprocess.run(
        [str(docker), "exec", container, "cat", "/deployment/registry.json"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise RuntimeError("ResContract registry must be an object")
    return value


def _services(
    *,
    docker: Path,
    docker_host: str | None,
    resdb_container: str,
    contract_container: str,
    registry: Mapping[str, object],
    event_key: bytes,
    now: datetime,
    crash_after_contract: bool = False,
) -> tuple[GroupService, FinanceService]:
    store = DockerResilientDBEventStore(
        docker=docker,
        docker_host=docker_host,
        container=resdb_container,
        config_path="/config/client.config",
    )
    repository = EncryptedEventRepository(
        store,
        AesGcmCipher(event_key, key_id="milestone4-acceptance-v1"),
        clock=lambda: now,
    )
    finance = FinanceService(repository)
    contract = DockerResContractCliGateway(
        docker=docker,
        docker_host=docker_host,
        container=contract_container,
        config_path="/config/client.config",
        contract_address=str(registry["contract_address"]),
        gateway_caller=str(registry["gateway_caller"]),
    )

    def crash(_: str) -> None:
        raise InjectedSagaCrash("injected after confirmed contract settlement")

    groups = GroupService(
        repository,
        contract,
        finance,
        clock=lambda: now,
        after_contract=crash if crash_after_contract else None,
    )
    return groups, finance


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
            "rescontract-1",
            "rescontract-2",
            "rescontract-3",
            "rescontract-4",
            "rescontract-proxy",
        ]
    )
    subprocess.run(command, cwd=REPOSITORY_ROOT, check=True, timeout=180)
    wait_command = [str(docker)]
    if docker_host:
        wait_command.extend(["--host", docker_host])
    wait_command.extend(["compose", "--profile", "tools", "up", "-d", "--wait"])
    subprocess.run(wait_command, cwd=REPOSITORY_ROOT, check=True, timeout=240)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the Milestone 4 real ResContract and ResilientDB acceptance."
    )
    parser.add_argument("--docker", type=Path, required=True)
    parser.add_argument("--docker-host")
    parser.add_argument("--resdb-container", default="resfinance-resdb-tools")
    parser.add_argument(
        "--contract-container", default="resfinance-rescontract-tools"
    )
    parser.add_argument("--restart", action="store_true")
    args = parser.parse_args()

    now = datetime.now(UTC).replace(microsecond=0)
    suffix = uuid.uuid4().hex[:12]
    group_id = f"m4-{suffix}"
    expense_id = f"expense-{suffix}"
    event_key = secrets.token_bytes(32)
    payer_key, payer = _wallet()
    debtor_key, debtor = _wallet()
    registry = _registry(args.docker, args.contract_container)
    groups, finance = _services(
        docker=args.docker,
        docker_host=args.docker_host,
        resdb_container=args.resdb_container,
        contract_container=args.contract_container,
        registry=registry,
        event_key=event_key,
        now=now,
    )

    groups.create_group(
        actor_address=payer["address"],
        idempotency_key=f"create-{suffix}",
        expected_version=0,
        group_id=group_id,
        name="Milestone 4 acceptance",
        owner_display_name="Payer",
    )
    groups.add_member(
        actor_address=payer["address"],
        idempotency_key=f"member-{suffix}",
        expected_version=1,
        group_id=group_id,
        member_address=debtor["address"],
        display_name="Debtor",
    )
    expense_parameters: dict[str, object] = {
        "group_id": group_id,
        "expense_id": expense_id,
        "payer_address": payer["address"],
        "description": "Acceptance dinner",
        "amount_minor_units": 10_000,
        "occurred_on": now.date().isoformat(),
        "due_on": (now.date() + timedelta(days=14)).isoformat(),
        "shares": {payer["address"]: 4_000, debtor["address"]: 6_000},
        "expected_version": 2,
    }
    groups.create_expense(
        actor_address=payer["address"],
        idempotency_key=f"expense-{suffix}",
        expected_version=2,
        group_id=group_id,
        expense_id=expense_id,
        payer_address=payer["address"],
        description="Acceptance dinner",
        amount_minor_units=10_000,
        occurred_on=now.date(),
        due_on=now.date() + timedelta(days=14),
        shares={payer["address"]: 4_000, debtor["address"]: 6_000},
        intent=_intent(
            payer_key,
            payer,
            action="split.approve",
            resource_id=expense_id,
            parameters=expense_parameters,
            now=now,
        ),
        origin=ORIGIN,
    )
    obligation = next(
        iter(
            groups.overview(
                actor_address=debtor["address"], group_id=group_id
            ).obligations.values()
        )
    )
    decision_parameters: dict[str, object] = {
        "group_id": group_id,
        "obligation_id": obligation.obligation_id,
        "decision": "approve",
        "expected_version": 3,
    }
    groups.decide_obligation(
        actor_address=debtor["address"],
        idempotency_key=f"approve-{suffix}",
        expected_version=3,
        group_id=group_id,
        obligation_id=obligation.obligation_id,
        approve=True,
        intent=_intent(
            debtor_key,
            debtor,
            action="split.approve",
            resource_id=obligation.obligation_id,
            parameters=decision_parameters,
            now=now,
        ),
        origin=ORIGIN,
    )

    rejected_insufficient = False
    insufficient_parameters: dict[str, object] = {
        "group_id": group_id,
        "obligation_id": obligation.obligation_id,
        "amount_minor_units": 1,
        "expected_version": 4,
    }
    try:
        groups.settle_obligation(
            actor_address=debtor["address"],
            idempotency_key=f"insufficient-{suffix}",
            expected_version=4,
            group_id=group_id,
            obligation_id=obligation.obligation_id,
            amount_minor_units=1,
            intent=_intent(
                debtor_key,
                debtor,
                action="settlement.authorize",
                resource_id=obligation.obligation_id,
                parameters=insufficient_parameters,
                now=now,
            ),
            origin=ORIGIN,
        )
    except GroupRejected as exc:
        rejected_insufficient = "insufficient" in str(exc)
    if not rejected_insufficient:
        raise RuntimeError("insufficient-credit settlement was not rejected")

    fund_parameters: dict[str, object] = {
        "group_id": group_id,
        "amount_minor_units": 6_000,
        "expected_version": 4,
    }
    groups.fund_credits(
        actor_address=debtor["address"],
        idempotency_key=f"fund-{suffix}",
        expected_version=4,
        group_id=group_id,
        amount_minor_units=6_000,
        intent=_intent(
            debtor_key,
            debtor,
            action="credits.fund",
            resource_id=group_id,
            parameters=fund_parameters,
            now=now,
        ),
        origin=ORIGIN,
    )
    partial_parameters: dict[str, object] = {
        "group_id": group_id,
        "obligation_id": obligation.obligation_id,
        "amount_minor_units": 2_000,
        "expected_version": 5,
    }
    groups.settle_obligation(
        actor_address=debtor["address"],
        idempotency_key=f"partial-{suffix}",
        expected_version=5,
        group_id=group_id,
        obligation_id=obligation.obligation_id,
        amount_minor_units=2_000,
        intent=_intent(
            debtor_key,
            debtor,
            action="settlement.authorize",
            resource_id=obligation.obligation_id,
            parameters=partial_parameters,
            now=now,
        ),
        origin=ORIGIN,
    )

    full_parameters: dict[str, object] = {
        "group_id": group_id,
        "obligation_id": obligation.obligation_id,
        "amount_minor_units": 4_000,
        "expected_version": 7,
    }
    crashing, _ = _services(
        docker=args.docker,
        docker_host=args.docker_host,
        resdb_container=args.resdb_container,
        contract_container=args.contract_container,
        registry=registry,
        event_key=event_key,
        now=now,
        crash_after_contract=True,
    )
    try:
        crashing.settle_obligation(
            actor_address=debtor["address"],
            idempotency_key=f"full-{suffix}",
            expected_version=7,
            group_id=group_id,
            obligation_id=obligation.obligation_id,
            amount_minor_units=4_000,
            intent=_intent(
                debtor_key,
                debtor,
                action="settlement.authorize",
                resource_id=obligation.obligation_id,
                parameters=full_parameters,
                now=now,
            ),
            origin=ORIGIN,
        )
    except InjectedSagaCrash:
        pass
    else:
        raise RuntimeError("the settlement crash was not injected")

    if args.restart:
        _restart_stack(args.docker, args.docker_host)

    restarted, restarted_finance = _services(
        docker=args.docker,
        docker_host=args.docker_host,
        resdb_container=args.resdb_container,
        contract_container=args.contract_container,
        registry=registry,
        event_key=event_key,
        now=now,
    )
    repaired = restarted.reconcile_group(group_id)
    projection = restarted.overview(
        actor_address=debtor["address"], group_id=group_id
    )
    final_obligation = projection.obligations[obligation.obligation_id]
    month = now.strftime("%Y-%m")
    debtor_finance = restarted_finance.overview(
        actor_address=debtor["address"], month=month
    )
    payer_finance = restarted_finance.overview(
        actor_address=payer["address"], month=month
    )
    if final_obligation.status != ObligationStatus.SETTLED:
        raise RuntimeError("group obligation did not reconcile to settled")
    if debtor_finance.summary.payable_minor_units != 0:
        raise RuntimeError("debtor Finance projection did not reconcile")
    if payer_finance.summary.receivable_minor_units != 0:
        raise RuntimeError("payer Finance projection did not reconcile")
    if projection.credit_balances.get(debtor["address"]) != 0:
        raise RuntimeError("debtor credit projection did not reconcile")
    if projection.credit_balances.get(payer["address"]) != 6_000:
        raise RuntimeError("creditor credit projection did not reconcile")

    print(
        json.dumps(
            {
                "contract_address": registry["contract_address"],
                "group_id": group_id,
                "group_projection_version": projection.projection_version,
                "obligation_status": final_obligation.status.value,
                "settled_minor_units": final_obligation.settled_minor_units,
                "debtor_credit_balance": projection.credit_balances[debtor["address"]],
                "creditor_credit_balance": projection.credit_balances[payer["address"]],
                "finance_payable_minor_units": debtor_finance.summary.payable_minor_units,
                "finance_receivable_minor_units": payer_finance.summary.receivable_minor_units,
                "repaired_confirmation_count": len(repaired),
                "full_stack_restart": args.restart,
                "private_material_transmitted": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
