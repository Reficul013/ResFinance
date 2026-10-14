from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from blockchain.wallet.spike_signer import ResVaultSpikeSigner, WalletSigningRejected
from server.app.api.settlement import create_app
from server.app.application.settlement import SettlementService, parameters_hash
from server.app.domain.settlement import (
    ContractReceipt,
    SettlementParameters,
)

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)


class FakeContract:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def settle(
        self,
        *,
        intent_hash: str,
        actor_address: str,
        nonce_hash: str,
        credit_units: int,
    ) -> ContractReceipt:
        self.calls.append(
            {
                "intent_hash": intent_hash,
                "actor_address": actor_address,
                "nonce_hash": nonce_hash,
                "credit_units": credit_units,
            }
        )
        return ContractReceipt(
            contract_address="0x1111111111111111111111111111111111111111",
            intent_hash=intent_hash,
            transaction_result="0x1",
            confirmed_credit_units=credit_units,
        )


class FakeEventStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def put(self, key: str, value: str) -> None:
        if key.startswith("event:") and key in self.values:
            raise AssertionError("events are append-only")
        self.values[key] = value


def signed_command(
    signer: ResVaultSpikeSigner,
    parameters: SettlementParameters,
    *,
    nonce: str = "nonce-0000000000000001",
) -> dict[str, object]:
    intent = signer.sign_intent(
        version=1,
        intent_id="intent-1",
        action="settlement.authorize",
        resource_id="group-1",
        parameters_hash=parameters_hash(parameters),
        nonce=nonce,
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
        audience="resfinance-api",
        network_id="pinned-local-network",
        requesting_origin="https://app.resfinance.local",
        approved=True,
    )
    return {"intent": intent, "parameters": parameters.canonical_payload()}


def client_and_ports() -> tuple[TestClient, FakeContract, FakeEventStore]:
    contract = FakeContract()
    events = FakeEventStore()
    service = SettlementService(contract, events, clock=lambda: NOW)
    return TestClient(create_app(service)), contract, events


def post(client: TestClient, body: dict[str, object], key: str = "idem-1"):
    return client.post(
        "/api/v1/groups/group-1/settlements",
        headers={
            "Idempotency-Key": key,
            "Origin": "https://app.resfinance.local",
        },
        json=body,
    )


def test_signed_intent_changes_contract_then_appends_event() -> None:
    client, contract, events = client_and_ports()
    command = signed_command(
        ResVaultSpikeSigner(), SettlementParameters(credit_units=100, expected_version=4)
    )

    response = post(client, command)

    assert response.status_code == 200
    assert response.json()["projection_version"] == 5
    assert contract.calls[0]["credit_units"] == 100
    event_key = f"event:{response.json()['event_id']}"
    event = json.loads(events.values[event_key])
    assert event["event_type"] == "settlement.confirmed"
    assert event["credit_units"] == 100


def test_idempotent_retry_does_not_call_contract_twice() -> None:
    client, contract, _ = client_and_ports()
    command = signed_command(
        ResVaultSpikeSigner(), SettlementParameters(credit_units=100, expected_version=0)
    )

    first = post(client, command)
    second = post(client, command)

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert len(contract.calls) == 1


def test_tampering_and_nonce_replay_are_rejected() -> None:
    client, contract, _ = client_and_ports()
    command = signed_command(
        ResVaultSpikeSigner(), SettlementParameters(credit_units=100, expected_version=0)
    )
    tampered = json.loads(json.dumps(command))
    tampered["parameters"]["credit_units"] = 101

    assert post(client, tampered).status_code == 422
    assert post(client, command).status_code == 200
    assert post(client, command, key="idem-2").status_code == 422
    assert len(contract.calls) == 1


def test_page_network_server_storage_and_logs_never_contain_private_material(
    caplog,
) -> None:
    client, contract, events = client_and_ports()
    signer = ResVaultSpikeSigner()
    with caplog.at_level(logging.DEBUG):
        command = signed_command(
            signer, SettlementParameters(credit_units=100, expected_version=0)
        )
        response = post(client, command)

    observable = json.dumps(
        {
            "page_and_network_request": command,
            "server_response": response.json(),
            "contract_calls": contract.calls,
            "resilientdb_records": events.values,
            "logs": caplog.text,
            "signer_display": repr(signer),
        }
    ).lower()

    assert response.status_code == 200
    for prohibited in ("private", "seed", "password", "derived_key", "mnemonic"):
        assert prohibited not in observable


def test_wallet_requires_exact_origin_and_explicit_approval() -> None:
    parameters = SettlementParameters(credit_units=100, expected_version=0)
    signer = ResVaultSpikeSigner()
    common = {
        "version": 1,
        "intent_id": "intent-1",
        "action": "settlement.authorize",
        "resource_id": "group-1",
        "parameters_hash": parameters_hash(parameters),
        "nonce": "nonce-0000000000000001",
        "issued_at": NOW,
        "expires_at": NOW + timedelta(minutes=5),
        "requesting_origin": "https://app.resfinance.local",
        "audience": "resfinance-api",
        "network_id": "pinned-local-network",
    }

    with pytest.raises(WalletSigningRejected, match="origin"):
        signer.sign_intent(
            **{**common, "requesting_origin": "https://evil.example"}, approved=True
        )
    with pytest.raises(WalletSigningRejected, match="approval"):
        signer.sign_intent(
            **common,
            approved=False,
        )
