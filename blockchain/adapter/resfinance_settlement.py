from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

from server.app.domain.groups import (
    ContractConfirmation,
    ContractObligationState,
    ObligationStatus,
)

_STATUS = {
    1: ObligationStatus.PENDING,
    2: ObligationStatus.OPEN,
    3: ObligationStatus.PARTIALLY_SETTLED,
    4: ObligationStatus.SETTLED,
    5: ObligationStatus.REJECTED,
    6: ObligationStatus.CANCELLED,
}
_OPERATION = {1: "create", 2: "approve", 3: "reject", 4: "fund", 5: "settle", 6: "cancel"}


class ResFinanceSettlementGateway(ABC):
    def __init__(self, *, contract_address: str, gateway_caller: str) -> None:
        self._contract_address = contract_address
        self._gateway_caller = gateway_caller

    @abstractmethod
    def _execute(self, function: str, parameters: list[str]) -> str: ...

    def create_obligation(
        self,
        *,
        operation_id: str,
        intent_hash: str,
        nonce_hash: str,
        creditor_address: str,
        debtor_address: str,
        amount_minor_units: int,
    ) -> ContractConfirmation:
        operation_hash = _id_hash(operation_id)
        try:
            existing = self.obligation(operation_id)
        except RuntimeError:
            existing = None
        if existing is not None:
            if (
                existing.creditor_address != creditor_address
                or existing.debtor_address != debtor_address
                or existing.amount_minor_units != amount_minor_units
            ):
                raise RuntimeError("ResContract obligation conflicts with the request")
            return ContractConfirmation(
                receipt_id=_receipt_id(operation_hash),
                intent_hash=intent_hash,
                operation="create",
                amount_minor_units=existing.amount_minor_units,
                obligation_status=existing.status,
            )
        self._require_true(
            "createObligation(uint256,uint256,uint256,uint256,uint256,uint256)",
            [
                _hex(operation_hash),
                _hex(intent_hash),
                _hex(nonce_hash),
                creditor_address,
                debtor_address,
                str(amount_minor_units),
            ],
        )
        return ContractConfirmation(
            receipt_id=_receipt_id(operation_hash),
            intent_hash=intent_hash,
            operation="create",
            amount_minor_units=amount_minor_units,
            obligation_status=ObligationStatus.PENDING,
        )

    def decide_obligation(
        self,
        *,
        intent_hash: str,
        nonce_hash: str,
        obligation_id: str,
        actor_address: str,
        approve: bool,
    ) -> ContractConfirmation:
        existing = self.receipt(intent_hash)
        expected_operation = "approve" if approve else "reject"
        if existing is not None:
            if existing.operation != expected_operation:
                raise RuntimeError("ResContract receipt conflicts with the decision")
            return existing
        self._require_true(
            "decideObligation(uint256,uint256,uint256,uint256,uint256)",
            [
                _hex(intent_hash),
                _hex(nonce_hash),
                _hex(_id_hash(obligation_id)),
                actor_address,
                "1" if approve else "2",
            ],
        )
        return self._confirmation(intent_hash)

    def fund_credits(
        self,
        *,
        intent_hash: str,
        nonce_hash: str,
        actor_address: str,
        amount_minor_units: int,
    ) -> ContractConfirmation:
        existing = self.receipt(intent_hash)
        if existing is not None:
            if (
                existing.operation != "fund"
                or existing.amount_minor_units != amount_minor_units
            ):
                raise RuntimeError("ResContract receipt conflicts with the funding")
            return existing
        self._require_true(
            "fundCredits(uint256,uint256,uint256,uint256)",
            [
                _hex(intent_hash),
                _hex(nonce_hash),
                actor_address,
                str(amount_minor_units),
            ],
        )
        return self._confirmation(intent_hash)

    def settle_obligation(
        self,
        *,
        intent_hash: str,
        nonce_hash: str,
        obligation_id: str,
        actor_address: str,
        amount_minor_units: int,
    ) -> ContractConfirmation:
        existing = self.receipt(intent_hash)
        if existing is not None:
            if (
                existing.operation != "settle"
                or existing.amount_minor_units != amount_minor_units
            ):
                raise RuntimeError("ResContract receipt conflicts with the settlement")
            return existing
        self._require_true(
            "settleObligation(uint256,uint256,uint256,uint256,uint256)",
            [
                _hex(intent_hash),
                _hex(nonce_hash),
                _hex(_id_hash(obligation_id)),
                actor_address,
                str(amount_minor_units),
            ],
        )
        return self._confirmation(intent_hash)

    def receipt(self, intent_hash: str) -> ContractConfirmation | None:
        operation = self._query("receiptOperation(uint256)", [_hex(intent_hash)])
        if operation == 0:
            return None
        return self._confirmation(intent_hash, operation=operation)

    def obligation(self, obligation_id: str) -> ContractObligationState:
        key = _hex(_id_hash(obligation_id))
        status_number = self._query("obligationStatus(uint256)", [key])
        status = _STATUS.get(status_number)
        if status is None:
            raise RuntimeError("ResContract obligation does not exist")
        return ContractObligationState(
            obligation_id=obligation_id,
            creditor_address=_address(
                self._query("obligationCreditor(uint256)", [key])
            ),
            debtor_address=_address(self._query("obligationDebtor(uint256)", [key])),
            amount_minor_units=self._query("obligationAmount(uint256)", [key]),
            settled_minor_units=self._query("obligationSettled(uint256)", [key]),
            status=status,
        )

    def credit_balance(self, actor_address: str) -> int:
        return self._query("creditBalance(uint256)", [actor_address])

    def _confirmation(
        self, intent_hash: str, *, operation: int | None = None
    ) -> ContractConfirmation:
        operation_number = operation or self._query(
            "receiptOperation(uint256)", [_hex(intent_hash)]
        )
        operation_name = _OPERATION.get(operation_number)
        if operation_name is None:
            raise RuntimeError("ResContract receipt does not exist")
        obligation_key = self._query("receiptObligation(uint256)", [_hex(intent_hash)])
        status = None
        if obligation_key:
            status_number = self._query(
                "obligationStatus(uint256)", [_hex(f"{obligation_key:064x}")]
            )
            status = _STATUS.get(status_number)
        return ContractConfirmation(
            receipt_id=_receipt_id(intent_hash),
            intent_hash=intent_hash,
            operation=operation_name,
            amount_minor_units=self._query(
                "receiptAmount(uint256)", [_hex(intent_hash)]
            ),
            obligation_status=status,
            debtor_credit_balance=self._query(
                "receiptDebtorBalance(uint256)", [_hex(intent_hash)]
            ),
            creditor_credit_balance=self._query(
                "receiptCreditorBalance(uint256)", [_hex(intent_hash)]
            ),
        )

    def _require_true(self, function: str, parameters: list[str]) -> None:
        if _parse_result(self._execute(function, parameters)) != 1:
            raise RuntimeError("ResContract rejected the operation")

    def _query(self, function: str, parameters: list[str]) -> int:
        return _parse_result(self._execute(function, parameters))


class LocalResContractCliGateway(ResFinanceSettlementGateway):
    def __init__(
        self,
        *,
        tool: Path,
        config_path: Path,
        contract_address: str,
        gateway_caller: str,
    ) -> None:
        super().__init__(
            contract_address=contract_address, gateway_caller=gateway_caller
        )
        self._tool = tool
        self._config_path = config_path

    def _execute(self, function: str, parameters: list[str]) -> str:
        payload = _payload(
            function,
            parameters,
            contract_address=self._contract_address,
            gateway_caller=self._gateway_caller,
        )
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", suffix=".json"
        ) as handle:
            json.dump(payload, handle, separators=(",", ":"))
            handle.flush()
            completed = subprocess.run(
                [
                    str(self._tool),
                    "-c",
                    str(self._config_path),
                    "--config_file",
                    handle.name,
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
        return _extract_result(completed.stdout + completed.stderr)


class DockerResContractCliGateway(ResFinanceSettlementGateway):
    def __init__(
        self,
        *,
        docker: Path,
        docker_host: str | None,
        container: str,
        config_path: str,
        contract_address: str,
        gateway_caller: str,
    ) -> None:
        super().__init__(
            contract_address=contract_address, gateway_caller=gateway_caller
        )
        self._docker = docker
        self._docker_host = docker_host
        self._container = container
        self._config_path = config_path
        self._tool = "/app/bazel-bin/service/tools/contract/api_tools/contract_tools"

    def _docker_command(self, *args: str) -> list[str]:
        command = [str(self._docker)]
        if self._docker_host:
            command.extend(["--host", self._docker_host])
        return [*command, *args]

    def _execute(self, function: str, parameters: list[str]) -> str:
        payload = _payload(
            function,
            parameters,
            contract_address=self._contract_address,
            gateway_caller=self._gateway_caller,
        )
        remote_path = f"/tmp/resfinance-m4-{uuid.uuid4().hex}.json"
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", suffix=".json"
        ) as handle:
            json.dump(payload, handle, separators=(",", ":"))
            handle.flush()
            subprocess.run(
                self._docker_command(
                    "cp", handle.name, f"{self._container}:{remote_path}"
                ),
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
        try:
            completed = subprocess.run(
                self._docker_command(
                    "exec",
                    self._container,
                    self._tool,
                    "-c",
                    self._config_path,
                    "--config_file",
                    remote_path,
                ),
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            return _extract_result(completed.stdout + completed.stderr)
        finally:
            subprocess.run(
                self._docker_command(
                    "exec", self._container, "rm", "-f", remote_path
                ),
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )


def _payload(
    function: str,
    parameters: list[str],
    *,
    contract_address: str,
    gateway_caller: str,
) -> dict[str, str]:
    return {
        "command": "execute",
        "caller_address": gateway_caller,
        "contract_address": contract_address,
        "func_name": function,
        "params": ",".join(parameters),
    }


def _extract_result(output: str) -> str:
    marker = "execute result:"
    index = output.rfind(marker)
    if index < 0 or "execute contract fail" in output:
        raise RuntimeError("ResContract execution failed")
    lines = output[index + len(marker) :].strip().splitlines()
    if not lines:
        raise RuntimeError("ResContract returned no result")
    return lines[0].strip()


def _parse_result(value: str) -> int:
    return int(value, 16) if value.startswith("0x") else int(value)


def _id_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _hex(value: str) -> str:
    return value if value.startswith("0x") else f"0x{value}"


def _receipt_id(value: str) -> str:
    normalized = value.removeprefix("0x")
    return f"receipt-{normalized[:64]}"


def _address(value: int) -> str:
    return f"0x{value:040x}"
