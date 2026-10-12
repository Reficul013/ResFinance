from __future__ import annotations

import subprocess
from pathlib import Path


def parse_get_response(output: str, key: str) -> str | None:
    """Translate the KV CLI's empty-value missing-key convention."""
    prefix = f"get key = {key} value = "
    for line in output.splitlines():
        if line.startswith(prefix):
            value = line[len(prefix) :]
            return value if value else None
    if "get value fail" in output:
        return None
    raise RuntimeError(f"unexpected ResilientDB get response for {key}")


class DockerResilientDBEventStore:
    def __init__(
        self,
        *,
        docker: Path,
        docker_host: str,
        container: str,
        config_path: str,
    ) -> None:
        self._docker = docker
        self._docker_host = docker_host
        self._container = container
        self._config_path = config_path
        self._tool = "/app/bazel-bin/service/tools/kv/api_tools/kv_service_tools"

    def _run(self, command: str, key: str, value: str | None = None) -> str:
        args = [
            str(self._docker),
            "--host",
            self._docker_host,
            "exec",
            self._container,
            self._tool,
            "--config",
            self._config_path,
            "--cmd",
            command,
            "--key",
            key,
        ]
        if value is not None:
            args.extend(["--value", value])
        completed = subprocess.run(
            args,
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return completed.stdout

    def get(self, key: str) -> str | None:
        return parse_get_response(self._run("get", key), key)

    def put(self, key: str, value: str) -> None:
        output = self._run("set", key, value)
        if "ret = 0" not in output:
            raise RuntimeError(f"ResilientDB rejected write for {key}")
