from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = ROOT / ".resfinance-local"
PID_FILE = STATE_DIR / "client.pid"
CLIENT_LOG = STATE_DIR / "client.log"
MODEL_LOCK = ROOT / "config" / "milestone8-model-lock.json"
DEFAULT_MODEL_DIR = Path("/private/tmp/resfinance-qwen2.5-1.5b")
COMPOSE_SERVICES = (
    "resdb-1",
    "resdb-2",
    "resdb-3",
    "resdb-4",
    "resdb-proxy",
    "resdb-tools",
    "rescontract-1",
    "rescontract-2",
    "rescontract-3",
    "rescontract-4",
    "rescontract-proxy",
    "rescontract-init",
    "rescontract-tools",
    "api",
)
RESET_CONFIRMATION = "DELETE_LOCAL_RESFINANCE_STATE"


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def _run(
    args: Sequence[str | Path],
    *,
    check: bool = True,
    capture: bool = False,
    env: dict[str, str] | None = None,
    cwd: Path = ROOT,
) -> subprocess.CompletedProcess[str]:
    rendered = [str(value) for value in args]
    return subprocess.run(
        rendered,
        cwd=cwd,
        check=check,
        text=True,
        capture_output=capture,
        env=env,
    )


def _command_version(command: str, *args: str) -> str | None:
    executable = shutil.which(command)
    if executable is None:
        return None
    completed = _run((executable, *args), check=False, capture=True)
    if completed.returncode != 0:
        return None
    return (completed.stdout or completed.stderr).strip()


def _major(version: str) -> int | None:
    digits = ""
    for character in version.lstrip("vPython "):
        if character.isdigit():
            digits += character
        else:
            break
    return int(digits) if digits else None


def verify_model(model_dir: Path) -> list[Check]:
    lock = json.loads(MODEL_LOCK.read_text(encoding="utf-8"))["model"]
    checks: list[Check] = []
    for filename, field in (
        ("model.safetensors", "weights_sha256"),
        ("config.json", "config_sha256"),
        ("tokenizer_config.json", "tokenizer_config_sha256"),
    ):
        path = model_dir / filename
        if not path.is_file():
            checks.append(Check(f"model:{filename}", False, f"missing {path}"))
            continue
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        actual = digest.hexdigest()
        checks.append(
            Check(
                f"model:{filename}",
                actual == lock[field],
                actual if actual == lock[field] else f"hash mismatch: {actual}",
            )
        )
    return checks


def preflight(*, model_dir: Path | None, require_model: bool) -> list[Check]:
    docker = _command_version("docker", "version", "--format", "{{.Server.Version}}")
    compose = _command_version("docker", "compose", "version", "--short")
    node = _command_version("node", "--version")
    npm = _command_version("npm", "--version")
    python = _command_version(str(ROOT / ".venv" / "bin" / "python"), "--version")
    checks = [
        Check("architecture", platform.machine() == "arm64", platform.machine()),
        Check("docker-engine", docker is not None, docker or "unavailable"),
        Check("docker-compose", compose is not None, compose or "unavailable"),
        Check("node", node is not None and _major(node) == 22, node or "unavailable"),
        Check("npm", npm is not None, npm or "unavailable"),
        Check(
            "python",
            python is not None and python.startswith("Python 3.13"),
            python or "unavailable",
        ),
        Check(
            "client-dependencies",
            (ROOT / "client" / "node_modules" / ".package-lock.json").is_file(),
            "installed" if (ROOT / "client" / "node_modules").is_dir() else "run npm ci in client",
        ),
        Check(
            "reswallet-dependencies",
            (ROOT / "reswallet" / "node_modules" / ".package-lock.json").is_file(),
            (
                "installed"
                if (ROOT / "reswallet" / "node_modules").is_dir()
                else "run npm ci in reswallet"
            ),
        ),
    ]
    selected = model_dir or DEFAULT_MODEL_DIR
    if require_model or selected.exists():
        checks.extend(verify_model(selected))
    else:
        checks.append(
            Check("ai-model", True, "optional; deterministic evidence templates will be used")
        )
    return checks


def _print_checks(checks: Sequence[Check]) -> None:
    for check in checks:
        print(f"{'PASS' if check.ok else 'FAIL'} {check.name}: {check.detail}")


def _require_preflight(model_dir: Path | None, require_model: bool) -> None:
    checks = preflight(model_dir=model_dir, require_model=require_model)
    _print_checks(checks)
    failures = [check.name for check in checks if not check.ok]
    if failures:
        raise RuntimeError("preflight failed: " + ", ".join(failures))


def _compose(model_dir: Path | None = None) -> list[str]:
    command = ["docker", "compose", "-f", str(ROOT / "docker-compose.yml")]
    if model_dir is not None:
        command.extend(("-f", str(ROOT / "docker-compose.ai.yml")))
    command.extend(("--profile", "tools", "--profile", "app"))
    return command


def _compose_env(model_dir: Path | None) -> dict[str, str]:
    environment = dict(os.environ)
    if model_dir is not None:
        environment["RESFINANCE_AI_MODEL_PATH"] = str(model_dir.resolve())
    return environment


def _wait_for_http(url: str, *, timeout_seconds: float = 120.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
                last_error = RuntimeError(f"HTTP {response.status}")
        except (OSError, urllib.error.URLError) as exc:
            last_error = exc
        time.sleep(0.5)
    raise RuntimeError(f"health wait timed out for {url}: {last_error}")


def _client_running() -> bool:
    if not PID_FILE.is_file():
        return False
    try:
        os.kill(int(PID_FILE.read_text(encoding="utf-8")), 0)
    except (OSError, ValueError):
        PID_FILE.unlink(missing_ok=True)
        return False
    return True


def _start_client() -> None:
    if _client_running():
        return
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    log = CLIENT_LOG.open("ab")
    process = subprocess.Popen(
        ["npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", "5173", "--strictPort"],
        cwd=ROOT / "client",
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    log.close()
    PID_FILE.write_text(f"{process.pid}\n", encoding="utf-8")
    time.sleep(0.5)
    exit_code = process.poll()
    if exit_code is not None:
        PID_FILE.unlink(missing_ok=True)
        raise RuntimeError(
            "client process exited during startup; port 5173 may already be owned "
            f"by another process (exit {exit_code}; see {CLIENT_LOG})"
        )


def _stop_client() -> None:
    if not _client_running():
        return
    pid = int(PID_FILE.read_text(encoding="utf-8"))
    os.killpg(pid, signal.SIGTERM)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            break
        time.sleep(0.1)
    else:
        os.killpg(pid, signal.SIGKILL)
    PID_FILE.unlink(missing_ok=True)


def start(*, model_dir: Path | None, require_model: bool) -> None:
    selected_model = model_dir.resolve() if model_dir is not None else None
    _require_preflight(selected_model, require_model)
    _run(("npm", "run", "build"), cwd=ROOT / "reswallet")
    _run(("npm", "run", "build"), cwd=ROOT / "client")
    _run(
        (
            *_compose(selected_model),
            "up",
            "-d",
            "--build",
            "--wait",
            "--wait-timeout",
            "180",
            *COMPOSE_SERVICES,
        ),
        env=_compose_env(selected_model),
    )
    _start_client()
    try:
        _wait_for_http("http://127.0.0.1:8000/api/v1/health")
        _wait_for_http("http://127.0.0.1:5173/api/v1/health")
    except Exception:
        print("Startup failed; component logs follow.", file=sys.stderr)
        logs(tail=80, model_dir=selected_model)
        raise
    print("ResFinance local stack is healthy at http://127.0.0.1:5173")


def stop(*, model_dir: Path | None) -> None:
    _stop_client()
    _run((*_compose(model_dir), "stop"), check=False, env=_compose_env(model_dir))


def restart(*, model_dir: Path | None, require_model: bool) -> None:
    selected_model = model_dir.resolve() if model_dir is not None else None
    _require_preflight(selected_model, require_model)
    _stop_client()
    _run(
        (*_compose(selected_model), "restart", *COMPOSE_SERVICES),
        env=_compose_env(selected_model),
    )
    _start_client()
    _wait_for_http("http://127.0.0.1:8000/api/v1/health")
    _wait_for_http("http://127.0.0.1:5173/api/v1/health")
    print("ResFinance local stack restarted with persisted volumes intact.")


def status(*, model_dir: Path | None) -> int:
    completed = _run(
        (
            *_compose(model_dir),
            "ps",
            "--format",
            "table {{.Service}}\t{{.Status}}",
        ),
        check=False,
        capture=True,
        env=_compose_env(model_dir),
    )
    print(completed.stdout.rstrip())
    client_running = _client_running()
    print(json.dumps({"client_running": client_running, "client_log": str(CLIENT_LOG)}))
    api_ok = False
    client_ok = False
    try:
        _wait_for_http("http://127.0.0.1:8000/api/v1/health", timeout_seconds=2)
        api_ok = True
    except RuntimeError:
        pass
    try:
        _wait_for_http("http://127.0.0.1:5173/api/v1/health", timeout_seconds=2)
        client_ok = True
    except RuntimeError:
        pass
    print(json.dumps({"api_healthy": api_ok, "client_proxy_healthy": client_ok}))
    return 0 if completed.returncode == 0 and client_running and api_ok and client_ok else 1


def logs(*, tail: int, model_dir: Path | None) -> None:
    _run(
        (*_compose(model_dir), "logs", "--tail", str(tail)),
        check=False,
        env=_compose_env(model_dir),
    )
    if CLIENT_LOG.is_file():
        print(f"\n==> {CLIENT_LOG} <==")
        lines = CLIENT_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
        print("\n".join(lines[-tail:]))


def reset(*, confirmation: str, model_dir: Path | None) -> None:
    if confirmation != RESET_CONFIRMATION:
        raise RuntimeError(f"reset requires --confirm {RESET_CONFIRMATION}")
    _stop_client()
    _run(
        (*_compose(model_dir), "down", "--volumes", "--remove-orphans"),
        env=_compose_env(model_dir),
    )
    shutil.rmtree(STATE_DIR, ignore_errors=True)
    print("Deleted disposable local Compose volumes and client runtime state.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ResFinance Milestone 9 local lifecycle")
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--require-model", action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("preflight")
    commands.add_parser("start")
    commands.add_parser("status")
    commands.add_parser("stop")
    commands.add_parser("restart")
    log_parser = commands.add_parser("logs")
    log_parser.add_argument("--tail", type=int, default=100)
    reset_parser = commands.add_parser("reset")
    reset_parser.add_argument("--confirm", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    model_dir = args.model_dir.resolve() if args.model_dir else None
    if args.command == "preflight":
        checks = preflight(model_dir=model_dir, require_model=args.require_model)
        _print_checks(checks)
        return 0 if all(check.ok for check in checks) else 1
    if args.command == "start":
        start(model_dir=model_dir, require_model=args.require_model)
    elif args.command == "status":
        return status(model_dir=model_dir)
    elif args.command == "stop":
        stop(model_dir=model_dir)
    elif args.command == "restart":
        restart(model_dir=model_dir, require_model=args.require_model)
    elif args.command == "logs":
        logs(tail=args.tail, model_dir=model_dir)
    elif args.command == "reset":
        reset(confirmation=args.confirm, model_dir=model_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
