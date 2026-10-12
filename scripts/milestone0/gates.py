from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, cast

Status = Literal["pass", "fail", "blocked", "partial"]
ALLOWED_ASSETS = ("BTC", "ETH", "SOL")


@dataclass(frozen=True)
class GateResult:
    gate: str
    status: Status
    summary: str
    evidence: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def load_lock(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("unsupported milestone lock schema")
    return value


def validate_assets(assets: list[str] | tuple[str, ...]) -> None:
    if tuple(assets) != ALLOWED_ASSETS:
        raise ValueError(f"assets must be exactly {ALLOWED_ASSETS!r}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _deterministic_block(index: int, length: int) -> bytes:
    seed = hashlib.sha256(f"resfinance-m0:{index}".encode()).digest()
    repetitions = (length + len(seed) - 1) // len(seed)
    return (seed * repetitions)[:length]


def chunk_round_trip(
    size_bytes: int,
    chunk_size: int = 256 * 1024,
    directory: Path | None = None,
) -> dict[str, object]:
    if size_bytes <= 0 or chunk_size <= 0:
        raise ValueError("size and chunk size must be positive")

    owned_directory = directory is None
    work = directory or Path(tempfile.mkdtemp(prefix="resfinance-m0-blob-"))
    chunks = work / "chunks"
    source = work / "checkpoint.bin"
    restored = work / "restored.bin"
    chunks.mkdir(parents=True, exist_ok=True)

    try:
        remaining = size_bytes
        source_hash = hashlib.sha256()
        manifest: list[dict[str, object]] = []
        with source.open("wb") as output:
            index = 0
            while remaining:
                length = min(chunk_size, remaining)
                payload = _deterministic_block(index, length)
                output.write(payload)
                source_hash.update(payload)
                chunk_hash = hashlib.sha256(payload).hexdigest()
                chunk_path = chunks / f"{index:06d}-{chunk_hash}.bin"
                chunk_path.write_bytes(payload)
                manifest.append(
                    {"index": index, "size": length, "sha256": chunk_hash}
                )
                remaining -= length
                index += 1

        restored_hash = hashlib.sha256()
        with restored.open("wb") as output:
            for item in manifest:
                index = cast(int, item["index"])
                expected = str(item["sha256"])
                matches = list(chunks.glob(f"{index:06d}-{expected}.bin"))
                if len(matches) != 1:
                    raise RuntimeError(f"chunk {index} is missing or ambiguous")
                payload = matches[0].read_bytes()
                if hashlib.sha256(payload).hexdigest() != expected:
                    raise RuntimeError(f"chunk {index} failed checksum verification")
                output.write(payload)
                restored_hash.update(payload)

        result = {
            "size_bytes": size_bytes,
            "chunk_size": chunk_size,
            "chunk_count": len(manifest),
            "source_sha256": source_hash.hexdigest(),
            "restored_sha256": restored_hash.hexdigest(),
            "identical": source_hash.digest() == restored_hash.digest(),
        }
        if not result["identical"]:
            raise RuntimeError("restored artifact checksum differs")
        return result
    finally:
        if owned_directory:
            shutil.rmtree(work)


def command_version(command: str, args: list[str]) -> dict[str, object]:
    executable = shutil.which(command)
    if executable is None:
        return {"available": False, "command": command}
    completed = subprocess.run(
        [executable, *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    output = (completed.stdout or completed.stderr).strip().splitlines()
    return {
        "available": completed.returncode == 0,
        "command": command,
        "path": executable,
        "version_output": output[0] if output else "",
        "returncode": completed.returncode,
    }


def inspect_upstream(upstream: Path, expected_commit: str) -> GateResult:
    if not (upstream / ".git").exists():
        return GateResult(
            "upstream-source",
            "blocked",
            "Pinned upstream checkout is unavailable.",
            {"expected_commit": expected_commit, "path": str(upstream)},
        )
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=upstream,
        check=False,
        capture_output=True,
        text=True,
    )
    actual = completed.stdout.strip()
    status: Status = "pass" if actual == expected_commit else "fail"
    return GateResult(
        "upstream-source",
        status,
        "Pinned upstream source matches." if status == "pass" else "Upstream commit mismatch.",
        {"expected_commit": expected_commit, "actual_commit": actual},
    )


def audit_resvault(upstream: Path) -> GateResult:
    files = {
        "content": upstream / "ecosystem/tools/resvault/public/content.js",
        "background": upstream / "ecosystem/tools/resvault/public/background.js",
        "manifest": upstream / "ecosystem/tools/resvault/public/manifest.json",
        "login": upstream / "ecosystem/tools/resvault/src/pages/Login.jsx",
    }
    if any(not path.exists() for path in files.values()):
        return GateResult(
            "resvault-key-isolation",
            "blocked",
            "ResVault audit inputs are unavailable.",
            {name: str(path) for name, path in files.items()},
        )

    content = files["content"].read_text(encoding="utf-8")
    background = files["background"].read_text(encoding="utf-8")
    login = files["login"].read_text(encoding="utf-8")
    findings = {
        "private_key_posted_to_page": "privateKey: response.privateKey" in content,
        "background_returns_decrypted_private_key": (
            "privateKey: decryptedPrivateKey" in background
        ),
        "password_persisted_in_local_storage": (
            "chrome.storage.local.set({ password: loginValues.password }" in login
        ),
        "exportable_aes_key_stored_with_ciphertext": (
            "crypto.subtle.exportKey('jwk', keyMaterial)" in background
            and "exportedKey: exportedKey" in background
        ),
        "content_script_matches_all_urls": '"matches": ["<all_urls>"]'
        in files["manifest"].read_text(encoding="utf-8"),
    }
    unsafe = [name for name, present in findings.items() if present]
    return GateResult(
        "resvault-key-isolation",
        "fail" if unsafe else "pass",
        (
            "Pinned upstream ResVault violates the ResFinance key-isolation contract."
            if unsafe
            else "No prohibited key-isolation patterns were detected."
        ),
        {"findings": findings, "required_path": "substantial-hardening" if unsafe else "upstream"},
    )


def scan_forbidden_persistence(repo: Path) -> GateResult:
    roots = [repo / name for name in ("client", "server", "blockchain", "ml")]
    needles = (
        "import sqlite3",
        "from sqlite3",
        "psycopg",
        "pymongo",
        "duckdb",
        "redis://",
        "postgresql://",
        "write_parquet(",
    )
    findings: list[str] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".ts", ".tsx", ".js", ".jsx"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
            for needle in needles:
                if needle.lower() in text:
                    findings.append(f"{path.relative_to(repo)}:{needle}")
    return GateResult(
        "sole-database-enforcement",
        "fail" if findings else "pass",
        (
            "Forbidden persistence dependency detected."
            if findings
            else "No forbidden persistence implementation detected."
        ),
        {"findings": findings},
    )


def aggregate_status(results: list[GateResult]) -> Status:
    statuses = {result.status for result in results}
    if "fail" in statuses:
        return "fail"
    if "blocked" in statuses:
        return "blocked"
    if "partial" in statuses:
        return "partial"
    return "pass"


def environment_evidence() -> dict[str, object]:
    return {
        "python": command_version("python3", ["--version"]),
        "node": command_version("node", ["--version"]),
        "docker": command_version("docker", ["--version"]),
        "solc": command_version("solc", ["--version"]),
        "host_arch": os.uname().machine,
    }
