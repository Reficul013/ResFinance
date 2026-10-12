from __future__ import annotations

import json
import subprocess
import tempfile
import uuid
from pathlib import Path

from server.app.domain.settlement import ContractReceipt


class DockerResContractGateway:
    def __init__(
        self,
        *,
        docker: Path,
        docker_host: str,
        container: str,
        config_path: str,
        contract_address: str,
        gateway_caller: str,
    ) -> None:
        self._docker = docker
        self._docker_host = docker_host
        self._container = container
        self._config_path = config_path
        self._contract_address = contract_address
        self._gateway_caller = gateway_caller
        self._tool = "/app/bazel-bin/service/tools/contract/api_tools/contract_tools"

    def _docker_command(self, *args: str) -> list[str]:
        return [str(self._docker), "--host", self._docker_host, *args]

    def _execute(self, function: str, parameters: list[str]) -> str:
        payload = {
            "command": "execute",
            "caller_address": self._gateway_caller,
            "contract_address": self._contract_address,
            "func_name": function,
            "params": ",".join(parameters),
        }
        remote_path = f"/tmp/resfinance-{uuid.uuid4().hex}.json"
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json") as handle:
            json.dump(payload, handle, separators=(",", ":"))
            handle.flush()
            subprocess.run(
                self._docker_command("cp", handle.name, f"{self._container}:{remote_path}"),
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
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
        combined = completed.stdout + completed.stderr
        marker = "execute result:"
        marker_index = combined.rfind(marker)
        if marker_index < 0 or "execute contract fail" in combined:
            raise RuntimeError("ResContract execution failed")
        result_lines = combined[marker_index + len(marker) :].strip().splitlines()
        if not result_lines:
            raise RuntimeError("ResContract returned no result")
        return result_lines[0].strip()

    def settle(
        self,
        *,
        intent_hash: str,
        actor_address: str,
        nonce_hash: str,
        credit_units: int,
    ) -> ContractReceipt:
        transaction_result = self._execute(
            "settle(uint256,uint256,uint256,uint256)",
            [
                f"0x{intent_hash}",
                actor_address,
                f"0x{nonce_hash}",
                str(credit_units),
            ],
        )
        if int(transaction_result, 16) != 1:
            raise RuntimeError("ResContract rejected settlement")
        confirmed = int(
            self._execute("creditUnitsFor(uint256)", [f"0x{intent_hash}"]), 16
        )
        return ContractReceipt(
            contract_address=self._contract_address,
            intent_hash=intent_hash,
            transaction_result=transaction_result,
            confirmed_credit_units=confirmed,
        )
