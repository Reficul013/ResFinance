from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

TOOL = Path(
    os.environ.get(
        "RESFINANCE_RESCONTRACT_TOOL",
        "/app/bazel-bin/service/tools/contract/api_tools/contract_tools",
    )
)
CONFIG = Path(
    os.environ.get("RESFINANCE_RESCONTRACT_CONFIG", "/config/client.config")
)
COMPILED = Path(
    os.environ.get("RESFINANCE_RESCONTRACT_COMPILED", "/deployment/contract.json")
)
REGISTRY = Path(
    os.environ.get("RESFINANCE_RESCONTRACT_REGISTRY", "/deployment/registry.json")
)
CONTRACT_NAME = "ResFinanceSettlement"
ADDRESS = re.compile(r'(?:address|contract_address): "(0x[0-9a-fA-F]+)"')


def _run(payload: dict[str, str]) -> str:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json") as handle:
        json.dump(payload, handle, separators=(",", ":"))
        handle.flush()
        completed = subprocess.run(
            [str(TOOL), "-c", str(CONFIG), "--config_file", handle.name],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
    output = completed.stdout + completed.stderr
    if " fail" in output:
        raise RuntimeError(output.strip())
    return output


def _address(output: str) -> str:
    matches = ADDRESS.findall(output)
    if not matches:
        raise RuntimeError(f"ResContract did not return an address: {output.strip()}")
    return matches[-1].lower()


def _compiled_contract_key() -> str:
    document = json.loads(COMPILED.read_text(encoding="utf-8"))
    contracts = document.get("contracts")
    if not isinstance(contracts, dict):
        raise RuntimeError("compiled contract manifest is missing contracts")
    matches = [key for key in contracts if key.endswith(f":{CONTRACT_NAME}")]
    if len(matches) != 1:
        raise RuntimeError("compiled contract manifest has an ambiguous contract key")
    return matches[0]


def main() -> int:
    compiled_sha256 = hashlib.sha256(COMPILED.read_bytes()).hexdigest()
    if REGISTRY.exists():
        current = json.loads(REGISTRY.read_text(encoding="utf-8"))
        if current.get("compiled_sha256") == compiled_sha256:
            print(json.dumps(current, sort_keys=True))
            return 0

    caller = _address(_run({"command": "create_account"}))
    contract_key = _compiled_contract_key()
    contract = _address(
        _run(
            {
                "command": "deploy",
                "contract_path": str(COMPILED),
                "contract_name": contract_key,
                "contract_address": caller,
                "init_params": "",
            }
        )
    )
    registry = {
        "schema_version": 1,
        "compiler": "0.8.28",
        "compiled_sha256": compiled_sha256,
        "contract_name": CONTRACT_NAME,
        "contract_address": contract,
        "gateway_caller": caller,
    }
    temporary = REGISTRY.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(REGISTRY)
    print(json.dumps(registry, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
