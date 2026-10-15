from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import platform
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from server.app.application.insights import MODEL_ID, MODEL_REVISION
from server.app.domain.insights import AuthorizedFact, AuthorizedFactBundle
from server.app.infrastructure.huggingface_insights import HuggingFaceInstructionSelector


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark the pinned local instruction model")
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-download", action="store_true")
    parser.add_argument("--runs", type=int, default=2)
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be positive")
    if not args.model_dir.exists():
        if not args.allow_download:
            parser.error("model directory is missing; pass --allow-download to fetch the pin")
        _download(args.model_dir)

    import torch

    psutil: Any = importlib.import_module("psutil")
    transformers: Any = importlib.import_module("transformers")

    process = psutil.Process()
    rss_before = process.memory_info().rss
    selector = HuggingFaceInstructionSelector(model_path=args.model_dir)
    bundle = _bundle()
    durations: list[float] = []
    selections: list[dict[str, Any]] = []
    for _ in range(args.runs):
        started = time.perf_counter()
        selection = selector.select_facts(
            question="Which recorded budget needs attention?",
            topics=("budgets",),
            bundle=bundle,
        )
        durations.append(time.perf_counter() - started)
        selections.append(
            {"fact_ids": list(selection.fact_ids), "confidence": selection.confidence}
        )
    rss_after = process.memory_info().rss
    expected = {"budget.groceries"}
    valid = all(
        set(value["fact_ids"]).issubset(expected) and bool(value["fact_ids"])
        for value in selections
    )
    evidence = {
        "schema_version": 1,
        "recorded_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "model": {
            "id": MODEL_ID,
            "revision": MODEL_REVISION,
            "model_dir": str(args.model_dir),
            "weights_sha256": _sha256(args.model_dir / "model.safetensors"),
            "config_sha256": _sha256(args.model_dir / "config.json"),
            "tokenizer_config_sha256": _sha256(args.model_dir / "tokenizer_config.json"),
        },
        "runtime": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "torch": torch.__version__,
            "transformers": transformers.__version__,
            "mps_available": torch.backends.mps.is_available(),
        },
        "benchmark": {
            "runs": args.runs,
            "durations_seconds": durations,
            "cold_seconds": durations[0],
            "warm_median_seconds": sorted(durations[1:] or durations)[
                len(durations[1:] or durations) // 2
            ],
            "rss_before_bytes": rss_before,
            "rss_after_bytes": rss_after,
            "rss_delta_bytes": max(0, rss_after - rss_before),
            "selections": selections,
            "valid_fact_selection": valid,
        },
        "policy": {
            "runtime_network_access": False,
            "trust_remote_code": False,
            "model_can_author_final_claims": False,
            "template_fallback_required": True,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2))
    return 0 if valid else 1


def _download(model_dir: Path) -> None:
    hub = __import__("huggingface_hub")
    snapshot_download: Any = hub.snapshot_download
    model_dir.parent.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=MODEL_ID,
        revision=MODEL_REVISION,
        local_dir=str(model_dir),
    )


def _bundle() -> AuthorizedFactBundle:
    fact = AuthorizedFact(
        fact_id="budget.groceries",
        topic="budgets",
        statement="Groceries is over budget at 110% ($1,100.00 of $1,000.00).",
        source_kind="finance-budget",
        source_ids=("evt-budget", "evt-expense"),
        as_of_utc=datetime(2026, 10, 14, tzinfo=UTC),
    )
    return AuthorizedFactBundle.build(
        actor_address="0x" + "a" * 40,
        month="2026-10",
        facts=(fact,),
    )


def _sha256(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    sys.exit(main())
