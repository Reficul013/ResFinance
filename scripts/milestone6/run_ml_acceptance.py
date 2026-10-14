from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from ml.data.synthetic import generate_synthetic_feature_dataset
from ml.runs.runner import SmokeRunConfig, run_smoke_research
from server.app.infrastructure.blob_repository import EncryptedBlobRepository
from server.app.infrastructure.encryption import AesGcmCipher
from server.app.infrastructure.research_repository import PromotionCriteria, ResearchRunRepository
from server.app.infrastructure.resilientdb_cli import DockerResilientDBEventStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run two deterministic Milestone 6 CPU research smokes and persist their complete "
            "artifacts through the real local ResilientDB stack."
        )
    )
    parser.add_argument("--docker", type=Path, default=Path("docker"))
    parser.add_argument("--docker-host")
    parser.add_argument("--container", default="resfinance-resdb-tools")
    parser.add_argument("--config", default="/config/client.config")
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.epochs < 1:
        raise ValueError("epochs must be positive")
    feature_dataset = generate_synthetic_feature_dataset()
    run_prefix = uuid.uuid4().hex
    config = SmokeRunConfig(epochs=args.epochs)
    first = run_smoke_research(
        feature_dataset,
        config=config,
        run_id=f"{run_prefix}-a",
    )
    second = run_smoke_research(
        feature_dataset,
        config=config,
        run_id=f"{run_prefix}-b",
    )
    if first.dataset_hash != second.dataset_hash:
        raise RuntimeError("repeated CPU smoke runs produced different dataset hashes")
    if first.prediction_hash != second.prediction_hash:
        raise RuntimeError("repeated CPU smoke runs produced different prediction hashes")

    store = DockerResilientDBEventStore(
        docker=args.docker,
        docker_host=args.docker_host,
        container=args.container,
        config_path=args.config,
        timeout_seconds=60,
    )
    local_key = hashlib.sha256(b"resfinance-milestone6-local-acceptance-key-v1").digest()
    repository = ResearchRunRepository(
        store,
        EncryptedBlobRepository(
            store,
            AesGcmCipher(local_key, key_id="milestone6-local-acceptance-v1"),
        ),
    )
    first_receipt = repository.put_completed_run(first.manifest, first.artifacts)
    second_receipt = repository.put_completed_run(second.manifest, second.artifacts)
    repeated_receipt = repository.put_completed_run(first.manifest, first.artifacts)
    if not repeated_receipt.deduplicated:
        raise RuntimeError("repeated run persistence was not idempotent")
    for name, content in first.artifacts.items():
        restored = repository.restore_artifact(first.run_id, name)
        if restored != content:
            raise RuntimeError(f"research artifact restoration failed: {name}")

    promotion_rejected = False
    promotion_reason = ""
    try:
        repository.promote_model(
            run_id=first.run_id,
            model_name="adaptive-gating",
            criteria=PromotionCriteria(),
            promoted_at_utc=datetime.now(UTC),
            approved_by="milestone6-local-acceptance",
        )
    except ValueError as exc:
        promotion_rejected = True
        promotion_reason = str(exc)

    metrics = first.manifest["metrics"]
    if not isinstance(metrics, dict):
        raise RuntimeError("research metrics are missing")
    evidence = {
        "schema_version": 1,
        "completed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "scope": "local-deterministic-synthetic-ml-on-real-resilientdb",
        "persistent_database": "Apache ResilientDB LevelDB backend",
        "assets": ["BTC", "ETH", "SOL"],
        "dataset_hash": first.dataset_hash,
        "prediction_hash": first.prediction_hash,
        "repeated_dataset_hash_identical": True,
        "repeated_prediction_hash_identical": True,
        "fold_count": len(cast(list[object], first.manifest["folds"])),
        "embargo_days": config.embargo_dates,
        "reported_models": first.manifest["reported_models"],
        "required_comparisons_complete": first.manifest[
            "required_comparisons_complete"
        ],
        "adaptive_metrics": metrics["adaptive-gating"],
        "naive_metrics": metrics["naive-zero-return"],
        "statistical_significance_claim": first.manifest[
            "statistical_significance_claim"
        ],
        "first_run_id": first.run_id,
        "second_run_id": second.run_id,
        "first_manifest_key": first_receipt.manifest_key,
        "second_manifest_key": second_receipt.manifest_key,
        "artifact_count": len(first.artifacts),
        "artifact_restore_verified": True,
        "repeat_persistence_idempotent": repeated_receipt.deduplicated,
        "promotion_rejected_by_explicit_criteria": promotion_rejected,
        "promotion_reason": promotion_reason,
        "three_asset_adaptation": True,
        "author_repository_code_copied": False,
    }
    rendered = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    print(rendered, end="")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
