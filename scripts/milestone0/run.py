from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from scripts.milestone0.gates import (
    GateResult,
    aggregate_status,
    audit_resvault,
    chunk_round_trip,
    environment_evidence,
    inspect_upstream,
    load_lock,
    scan_forbidden_persistence,
    validate_assets,
)
from scripts.milestone0.providers import probe_providers


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run ResFinance Milestone 0 checks")
    parser.add_argument(
        "--upstream",
        type=Path,
        default=Path("/private/tmp/resfinance-resilientdb-upstream"),
        help="path to the pinned Apache ResilientDB checkout",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="optional JSON evidence path (generated evidence should not be committed)",
    )
    parser.add_argument(
        "--blob-size-mib",
        type=int,
        default=100,
        help="local artifact round-trip size; acceptance requires 100",
    )
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="return zero even though mandatory real-stack gates are incomplete",
    )
    parser.add_argument(
        "--network",
        action="store_true",
        help="run read-only provider boundary probes",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo = Path(__file__).resolve().parents[2]
    lock = load_lock(repo / "config/milestone0-lock.json")
    period = lock["research_period"]
    if not isinstance(period, dict):
        raise TypeError("research_period must be an object")
    validate_assets(period["assets"])

    resilientdb = cast(dict[str, object], lock["resilientdb"])
    source = inspect_upstream(args.upstream, str(resilientdb["commit"]))
    wallet = audit_resvault(args.upstream)
    storage_policy = scan_forbidden_persistence(repo)
    local_blob = chunk_round_trip(args.blob_size_mib * 1024 * 1024)
    environment = environment_evidence()
    docker = cast(dict[str, object], environment["docker"])
    solc = cast(dict[str, object], environment["solc"])
    docker_available = bool(docker.get("available"))
    solc_available = bool(solc.get("available"))

    provider_evidence = (
        probe_providers()
        if args.network
        else {"period": period, "network_probes": "not-requested"}
    )

    results = [
        GateResult(
            "1-resilientdb-kv-durability-replica-loss",
            "blocked",
            "Real four-replica execution is required and has not run.",
            {"docker_available": docker_available},
        ),
        GateResult(
            "2-resilientdb-100mb-artifact",
            "partial",
            "Local 256 KiB chunk reconstruction passed; ResilientDB persistence is pending.",
            local_blob,
        ),
        GateResult(
            "3-rescontract-lifecycle",
            "blocked",
            "Compile/deploy/execute/query/restart requires the real pinned stack.",
            {"docker_available": docker_available, "solc_available": solc_available},
        ),
        GateResult(
            "4-signed-settlement-saga",
            "blocked",
            (
                "REST, signed intent, ResContract, and finance-event integration "
                "is not yet executable."
            ),
            {"dependency_gates": [1, 3, 5]},
        ),
        GateResult(
            "5-resvault-key-isolation",
            wallet.status,
            wallet.summary,
            wallet.evidence,
        ),
        GateResult(
            "6-provider-availability-provenance",
            "partial",
            (
                "Boundary probes are available; full-period acquisition and terms "
                "review remain pending."
            ),
            provider_evidence,
        ),
        GateResult(
            "7-failure-enforcement",
            storage_policy.status,
            storage_policy.summary,
            storage_policy.evidence,
        ),
    ]
    overall = aggregate_status(results)
    evidence = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "overall_status": overall,
        "source_check": source.to_dict(),
        "environment": environment,
        "gates": [result.to_dict() for result in results],
    }
    rendered = json.dumps(evidence, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if overall == "pass" or args.allow_incomplete else 2


if __name__ == "__main__":
    sys.exit(main())
