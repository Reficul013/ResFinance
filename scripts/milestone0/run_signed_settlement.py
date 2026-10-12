from __future__ import annotations

import argparse
import json
import secrets
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Keep this checked-in operator script directly executable without requiring an
# editable package install in the Milestone 0 virtual environment.
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from blockchain.adapter.rescontract_cli import DockerResContractGateway  # noqa: E402
from blockchain.wallet.spike_signer import ResVaultSpikeSigner  # noqa: E402
from server.app.api.settlement import create_app  # noqa: E402
from server.app.application.settlement import (  # noqa: E402
    SettlementService,
    parameters_hash,
)
from server.app.domain.settlement import SettlementParameters  # noqa: E402
from server.app.infrastructure.resilientdb_cli import (  # noqa: E402
    DockerResilientDBEventStore,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the signed REST-to-ResContract-to-ResilientDB feasibility spike."
    )
    parser.add_argument("--docker", type=Path, required=True)
    parser.add_argument("--docker-host", required=True)
    parser.add_argument("--container", required=True)
    parser.add_argument("--contract-address", required=True)
    parser.add_argument("--gateway-caller", required=True)
    args = parser.parse_args()

    contract = DockerResContractGateway(
        docker=args.docker,
        docker_host=args.docker_host,
        container=args.container,
        config_path="/app/service/tools/config/interface/contract-service.config",
        contract_address=args.contract_address,
        gateway_caller=args.gateway_caller,
    )
    events = DockerResilientDBEventStore(
        docker=args.docker,
        docker_host=args.docker_host,
        container=args.container,
        config_path="/app/service/tools/config/interface/service.config",
    )
    service = SettlementService(contract, events)
    client = TestClient(create_app(service))

    now = datetime.now(UTC).replace(microsecond=0)
    resource_id = f"group-m0-{uuid.uuid4().hex[:12]}"
    intent_id = f"intent-{uuid.uuid4().hex}"
    parameters = SettlementParameters(credit_units=125, expected_version=0)
    intent = ResVaultSpikeSigner().sign_intent(
        version=1,
        intent_id=intent_id,
        action="settlement.authorize",
        resource_id=resource_id,
        parameters_hash=parameters_hash(parameters),
        nonce=secrets.token_hex(16),
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
        audience="resfinance-api",
        network_id="pinned-local-network",
        requesting_origin="https://app.resfinance.local",
        approved=True,
    )
    response = client.post(
        f"/api/v1/groups/{resource_id}/settlements",
        headers={
            "Idempotency-Key": f"idem-{uuid.uuid4().hex}",
            "Origin": "https://app.resfinance.local",
        },
        json={"intent": intent, "parameters": parameters.canonical_payload()},
    )
    if response.status_code != 200:
        raise RuntimeError(f"signed settlement failed with HTTP {response.status_code}")
    result = response.json()
    stored_event = events.get(f"event:{result['event_id']}")
    if stored_event is None:
        raise RuntimeError("confirmed finance event was not stored")
    print(
        json.dumps(
            {
                "http_status": response.status_code,
                "result": result,
                "stored_event": json.loads(stored_event),
                "private_material_transmitted": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
