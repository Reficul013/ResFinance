from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from scripts.milestone0.gates import (
    GateResult,
    Status,
    aggregate_status,
    audit_resvault,
    chunk_round_trip,
    environment_evidence,
    inspect_upstream,
    load_lock,
    scan_forbidden_persistence,
    sha256_file,
    validate_assets,
)
from scripts.milestone0.providers import probe_providers

ATTESTED_GATE_NAMES = (
    "1-resilientdb-kv-durability-replica-loss",
    "2-resilientdb-100mb-artifact",
    "3-rescontract-lifecycle",
    "4-signed-settlement-saga",
    "5-resvault-key-isolation",
)
VALID_STATUSES: frozenset[str] = frozenset({"pass", "fail", "blocked", "partial"})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run ResFinance Milestone 0 checks")
    parser.add_argument(
        "--attestation",
        type=Path,
        help="sanitized local real-stack attestation; defaults to the checked record",
    )
    parser.add_argument(
        "--provider-attestation",
        type=Path,
        help="sanitized fixed-period provider attestation; defaults to the checked record",
    )
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


def load_attested_gates(path: Path) -> tuple[dict[str, object], list[GateResult]]:
    with path.open(encoding="utf-8") as handle:
        attestation = json.load(handle)
    if not isinstance(attestation, dict) or attestation.get("schema_version") != 1:
        raise ValueError("unsupported local attestation schema")
    values = attestation.get("gates")
    if not isinstance(values, list):
        raise ValueError("local attestation gates must be a list")
    results: list[GateResult] = []
    for value in values:
        if not isinstance(value, dict):
            raise ValueError("local attestation gate must be an object")
        gate = value.get("gate")
        status = value.get("status")
        summary = value.get("summary")
        evidence = value.get("evidence")
        if not isinstance(gate, str) or not isinstance(summary, str):
            raise ValueError("local attestation gate name and summary must be strings")
        if not isinstance(status, str) or status not in VALID_STATUSES:
            raise ValueError(f"invalid local attestation gate status: {status!r}")
        if not isinstance(evidence, dict):
            raise ValueError("local attestation gate evidence must be an object")
        results.append(
            GateResult(
                gate=gate,
                status=cast(Status, status),
                summary=summary,
                evidence=cast(dict[str, object], evidence),
            )
        )
    if tuple(result.gate for result in results) != ATTESTED_GATE_NAMES:
        raise ValueError("local attestation must contain gates 1 through 5 exactly once")
    return attestation, results


def load_provider_attestation(path: Path, *, query_path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        attestation = json.load(handle)
    if not isinstance(attestation, dict) or attestation.get("schema_version") != 1:
        raise ValueError("unsupported provider attestation schema")
    if attestation.get("status") != "pass":
        raise ValueError("provider attestation must have pass status")

    gdelt = attestation.get("gdelt_bigquery")
    persistence = attestation.get("resilientdb_persistence")
    if not isinstance(gdelt, dict) or not isinstance(persistence, dict):
        raise ValueError("provider attestation is missing GDELT or persistence evidence")
    if gdelt.get("query_sha256") != sha256_file(query_path):
        raise ValueError("provider attestation query digest does not match checked SQL")
    if gdelt.get("row_count") != 5_184:
        raise ValueError("provider attestation must contain the complete 5,184-row grid")
    rows_by_asset = gdelt.get("rows_by_asset")
    if rows_by_asset != {"BTC": 1_728, "ETH": 1_728, "SOL": 1_728}:
        raise ValueError("provider attestation must cover all three assets equally")
    if gdelt.get("billing_enabled") is not False:
        raise ValueError("provider attestation must come from billing-disabled sandbox")
    source_hash = persistence.get("source_sha256")
    if (
        persistence.get("identical") is not True
        or source_hash != persistence.get("restored_sha256")
        or source_hash != gdelt.get("csv_sha256")
    ):
        raise ValueError("provider artifact was not verified through ResilientDB")
    return cast(dict[str, object], attestation)


def main() -> int:
    args = parse_args()
    repo = Path(__file__).resolve().parents[2]
    attestation_path = args.attestation or repo / "config/milestone0-local-attestation.json"
    provider_attestation_path = (
        args.provider_attestation
        or repo / "config/milestone0-provider-attestation.json"
    )
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
    provider_attestation = load_provider_attestation(
        provider_attestation_path,
        query_path=repo / "scripts/milestone0/gdelt_bigquery.sql",
    )

    attestation, attested_results = load_attested_gates(attestation_path)
    if attestation.get("upstream_commit") != resilientdb["commit"]:
        raise ValueError("local attestation upstream commit does not match lock")
    local_container = lock.get("local_container")
    if not isinstance(local_container, dict):
        raise ValueError("local_container lock entry must be an object")
    if local_container.get("upstream_commit") != resilientdb["commit"]:
        raise ValueError("local container upstream commit does not match source pin")
    if attestation.get("image_digest") != local_container.get("image_digest"):
        raise ValueError("local attestation image digest does not match lock")
    if attestation.get("patch_sha256") != local_container.get("patch_sha256"):
        raise ValueError("local attestation patch digest does not match lock")
    patch_value = local_container.get("patch")
    if not isinstance(patch_value, str):
        raise ValueError("local container patch path must be a string")
    patch_path = repo / patch_value
    if sha256_file(patch_path) != local_container.get("patch_sha256"):
        raise ValueError("checked ResilientDB patch digest does not match lock")

    results = [
        *attested_results,
        GateResult(
            "6-provider-availability-provenance",
            "pass",
            (
                "Fixed-period prices and GDELT aggregates are proven and persisted; "
                "provider terms pass for the declared non-commercial research scope."
            ),
            {
                "current_probes": provider_evidence,
                "fixed_period_attestation": provider_attestation,
            },
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
        "local_attestation": {
            "path": str(attestation_path),
            "sha256": sha256_file(attestation_path),
            "official_resvault_audit": wallet.to_dict(),
            "local_blob_control": local_blob,
            "docker_detected_on_path": docker_available,
            "solc_detected_on_path": solc_available,
        },
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
