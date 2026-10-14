from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Sequence
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


def parse_range_response(output: str) -> list[str]:
    if "getrange value fail" in output:
        return []
    marker = "\n value = "
    if marker not in output:
        raise RuntimeError("unexpected ResilientDB range response")
    encoded = output.split(marker, maxsplit=1)[1].strip()
    try:
        values = json.loads(encoded)
    except json.JSONDecodeError as exc:
        raise RuntimeError("ResilientDB range response is not valid JSON") from exc
    if not isinstance(values, list):
        raise RuntimeError("ResilientDB range response must be a list")
    return [
        value
        if isinstance(value, str)
        else json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        for value in values
    ]


_VERSIONED_RANGE_ITEM = re.compile(
    r'item\s*\{\s*key:\s*"(?:\\.|[^"\\])*"\s*'
    r'value_info\s*\{\s*value:\s*"((?:\\.|[^"\\])*)"'
    r"(?:\s*version:\s*\d+)?\s*\}\s*\}",
    re.DOTALL,
)


def parse_versioned_range_response(output: str) -> list[str]:
    if "getrange value fail" in output:
        return []
    if "\n value = " not in output:
        raise RuntimeError("unexpected ResilientDB versioned range response")
    payload = output.split("\n value = ", maxsplit=1)[1]
    if not payload.strip():
        return []
    encoded_values = _VERSIONED_RANGE_ITEM.findall(payload)
    if not encoded_values:
        raise RuntimeError("ResilientDB versioned range response has no parseable items")
    values: list[str] = []
    for encoded in encoded_values:
        decoded = json.loads(f'"{encoded}"')
        if not isinstance(decoded, str):
            raise RuntimeError("ResilientDB versioned range value must be text")
        values.append(decoded)
    return values


class DockerResilientDBEventStore:
    def __init__(
        self,
        *,
        docker: Path,
        docker_host: str | None,
        container: str,
        config_path: str,
        timeout_seconds: int = 120,
    ) -> None:
        self._docker = docker
        self._docker_host = docker_host
        self._container = container
        self._config_path = config_path
        self._timeout_seconds = timeout_seconds
        self._tool = "/app/bazel-bin/service/tools/kv/api_tools/kv_service_tools"

    def _run(self, command: str, key: str, value: str | None = None) -> str:
        args = [str(self._docker)]
        if self._docker_host:
            args.extend(["--host", self._docker_host])
        args.extend(
            [
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
        )
        if value is not None:
            args.extend(["--value", value])
        completed = subprocess.run(
            args,
            check=True,
            capture_output=True,
            text=True,
            timeout=self._timeout_seconds,
        )
        return completed.stdout

    def get(self, key: str) -> str | None:
        return parse_get_response(self._run("get", key), key)

    def put(self, key: str, value: str) -> None:
        output = self._run("set", key, value)
        if "ret = 0" not in output:
            raise RuntimeError(f"ResilientDB rejected write for {key}")

    def range_values(self, prefix: str) -> Sequence[str]:
        args = [str(self._docker)]
        if self._docker_host:
            args.extend(["--host", self._docker_host])
        args.extend(
            [
            "exec",
            self._container,
            self._tool,
            "--config",
            self._config_path,
            "--cmd",
            "get_key_range_with_version",
            "--min_key",
            prefix,
            "--max_key",
            f"{prefix}~",
            ]
        )
        completed = subprocess.run(
            args,
            check=True,
            capture_output=True,
            text=True,
            timeout=self._timeout_seconds,
        )
        return parse_versioned_range_response(completed.stdout)


class ResilientDBCliStore:
    """Run the pinned KV client directly from the application container."""

    def __init__(
        self,
        *,
        tool: Path,
        config_path: Path,
        timeout_seconds: int = 30,
    ) -> None:
        self._tool = tool
        self._config_path = config_path
        self._timeout_seconds = timeout_seconds

    def _run(self, command: str, key: str, value: str | None = None) -> str:
        args = [
            str(self._tool),
            "--config",
            str(self._config_path),
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
            timeout=self._timeout_seconds,
        )
        return completed.stdout

    def get(self, key: str) -> str | None:
        return parse_get_response(self._run("get", key), key)

    def put(self, key: str, value: str) -> None:
        output = self._run("set", key, value)
        if "ret = 0" not in output:
            raise RuntimeError(f"ResilientDB rejected write for {key}")

    def range_values(self, prefix: str) -> Sequence[str]:
        args = [
            str(self._tool),
            "--config",
            str(self._config_path),
            "--cmd",
            "get_key_range_with_version",
            "--min_key",
            prefix,
            "--max_key",
            f"{prefix}~",
        ]
        completed = subprocess.run(
            args,
            check=True,
            capture_output=True,
            text=True,
            timeout=self._timeout_seconds,
        )
        return parse_versioned_range_response(completed.stdout)
