from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.milestone9 import local_handoff, run_full_research, run_local_workers


class MemoryStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def put(self, key: str, value: str) -> None:
        if key in self.values:
            raise ValueError("immutable key conflict")
        self.values[key] = value

    def range_values(self, prefix: str) -> Sequence[str]:
        return [self.values[key] for key in sorted(self.values) if key.startswith(prefix)]


def test_model_verification_checks_every_locked_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = {
        "model.safetensors": b"weights",
        "config.json": b"config",
        "tokenizer_config.json": b"tokenizer",
    }
    for name, content in files.items():
        (tmp_path / name).write_bytes(content)
    lock = tmp_path / "lock.json"
    lock.write_text(
        json.dumps(
            {
                "model": {
                    "weights_sha256": hashlib.sha256(files["model.safetensors"]).hexdigest(),
                    "config_sha256": hashlib.sha256(files["config.json"]).hexdigest(),
                    "tokenizer_config_sha256": hashlib.sha256(
                        files["tokenizer_config.json"]
                    ).hexdigest(),
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(local_handoff, "MODEL_LOCK", lock)

    checks = local_handoff.verify_model(tmp_path)

    assert len(checks) == 3
    assert all(check.ok for check in checks)


def test_model_verification_rejects_tampered_weights(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("model.safetensors", "config.json", "tokenizer_config.json"):
        (tmp_path / name).write_bytes(name.encode())
    lock = tmp_path / "lock.json"
    lock.write_text(
        json.dumps(
            {
                "model": {
                    "weights_sha256": "0" * 64,
                    "config_sha256": hashlib.sha256(b"config.json").hexdigest(),
                    "tokenizer_config_sha256": hashlib.sha256(
                        b"tokenizer_config.json"
                    ).hexdigest(),
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(local_handoff, "MODEL_LOCK", lock)

    checks = local_handoff.verify_model(tmp_path)

    assert checks[0].ok is False
    assert checks[1].ok is True
    assert checks[2].ok is True


def test_reset_requires_exact_confirmation() -> None:
    with pytest.raises(RuntimeError, match=local_handoff.RESET_CONFIRMATION):
        local_handoff.reset(confirmation="yes", model_dir=None)


def test_compose_overlay_is_opt_in() -> None:
    without_model = local_handoff._compose(None)
    with_model = local_handoff._compose(Path("/private/tmp/model"))

    assert "docker-compose.ai.yml" not in " ".join(without_model)
    assert "docker-compose.ai.yml" in " ".join(with_model)


def test_client_start_rejects_an_immediately_failed_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(local_handoff, "STATE_DIR", tmp_path)
    monkeypatch.setattr(local_handoff, "PID_FILE", tmp_path / "client.pid")
    monkeypatch.setattr(local_handoff, "CLIENT_LOG", tmp_path / "client.log")
    monkeypatch.setattr(local_handoff.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        local_handoff.subprocess,
        "Popen",
        lambda *args, **kwargs: SimpleNamespace(pid=321, poll=lambda: 1),
    )

    with pytest.raises(RuntimeError, match="port 5173"):
        local_handoff._start_client()

    assert not local_handoff.PID_FILE.exists()


@pytest.mark.parametrize(
    "arguments",
    [
        ["run_full_research", "--output", "/tmp/result.json"],
        [
            "run_full_research",
            "--ingest",
            "--dataset-hash",
            "0" * 64,
            "--output",
            "/tmp/result.json",
        ],
    ],
)
def test_full_research_requires_exactly_one_dataset_source(
    arguments: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "argv", arguments)

    with pytest.raises(ValueError, match="exactly one"):
        run_full_research.main()


def test_full_research_live_ingestion_requires_gdelt_export(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_full_research", "--ingest", "--output", "/tmp/result.json"],
    )

    with pytest.raises(ValueError, match="gdelt"):
        run_full_research.main()


def test_full_research_requires_runtime_artifact_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RESFINANCE_RESEARCH_ENCRYPTION_KEY", raising=False)
    with pytest.raises(ValueError, match="32-byte hexadecimal key"):
        run_full_research.load_encryption_key(
            "RESFINANCE_RESEARCH_ENCRYPTION_KEY"
        )

    monkeypatch.setenv("RESFINANCE_RESEARCH_ENCRYPTION_KEY", "ab" * 32)
    assert run_full_research.load_encryption_key(
        "RESFINANCE_RESEARCH_ENCRYPTION_KEY"
    ) == bytes.fromhex("ab" * 32)


def test_full_research_loads_persistent_container_key_when_env_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RESFINANCE_RESEARCH_ENCRYPTION_KEY", raising=False)
    monkeypatch.setattr(
        run_full_research.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=b"k" * 32),
    )

    key = run_full_research.load_research_key(
        variable="RESFINANCE_RESEARCH_ENCRYPTION_KEY",
        docker=Path("docker"),
        docker_host=None,
        container="resfinance-api-1",
        path="/certs/research-blob.key",
    )

    assert key == b"k" * 32


def test_worker_status_transitions_are_append_only_resilientdb_records() -> None:
    store = MemoryStore()
    started = datetime(2026, 10, 15, tzinfo=UTC)

    run_local_workers.write_status(store, "job-1", "running", started, None, {})
    run_local_workers.write_status(
        store,
        "job-1",
        "completed",
        started,
        started,
        {"inserted_count": 3},
    )

    assert sorted(store.values) == [
        "job:local:job-1:000-running",
        "job:local:job-1:100-terminal",
    ]
    assert json.loads(store.values["job:local:job-1:100-terminal"])["status"] == (
        "completed"
    )
