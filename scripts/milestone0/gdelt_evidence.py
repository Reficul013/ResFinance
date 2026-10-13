from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import TextIO

ASSETS = ("BTC", "ETH", "SOL")
PERIOD_START = date(2020, 4, 10)
PERIOD_END = date(2025, 1, 1)
COUNT_FIELDS = (
    "document_count",
    "source_count",
    "tone_observation_count",
    "positive_document_count",
    "negative_document_count",
    "neutral_document_count",
)
REQUIRED_FIELDS = ("day", "asset", *COUNT_FIELDS, "average_tone")


def _expected_keys(start: date, end: date) -> set[tuple[str, str]]:
    days = (end - start).days + 1
    return {
        ((start + timedelta(days=offset)).isoformat(), asset)
        for offset in range(days)
        for asset in ASSETS
    }


def validate_gdelt_csv(
    handle: TextIO, *, start: date = PERIOD_START, end: date = PERIOD_END
) -> dict[str, object]:
    reader = csv.DictReader(handle)
    if reader.fieldnames is None:
        raise ValueError("GDELT export has no CSV header")
    missing_fields = set(REQUIRED_FIELDS) - set(reader.fieldnames)
    if missing_fields:
        raise ValueError(f"GDELT export is missing fields: {sorted(missing_fields)}")

    expected = _expected_keys(start, end)
    observed: set[tuple[str, str]] = set()
    asset_rows: Counter[str] = Counter()
    total_documents = 0
    zero_document_rows = 0

    for line_number, row in enumerate(reader, start=2):
        key = (row["day"], row["asset"])
        if key in observed:
            raise ValueError(f"duplicate day/asset row at CSV line {line_number}: {key}")
        if key not in expected:
            raise ValueError(f"unexpected day/asset row at CSV line {line_number}: {key}")
        observed.add(key)
        asset_rows[row["asset"]] += 1

        counts: dict[str, int] = {}
        for field in COUNT_FIELDS:
            try:
                value = int(row[field])
            except ValueError as error:
                raise ValueError(
                    f"{field} is not an integer at CSV line {line_number}"
                ) from error
            if value < 0:
                raise ValueError(f"{field} is negative at CSV line {line_number}")
            counts[field] = value

        documents = counts["document_count"]
        tones = counts["tone_observation_count"]
        classified = (
            counts["positive_document_count"]
            + counts["negative_document_count"]
            + counts["neutral_document_count"]
        )
        if counts["source_count"] > documents:
            raise ValueError(f"source count exceeds documents at CSV line {line_number}")
        if tones > documents or classified != tones:
            raise ValueError(f"tone counts are inconsistent at CSV line {line_number}")

        average_tone = row["average_tone"].strip()
        if tones == 0 and average_tone:
            raise ValueError(f"average tone exists without observations at CSV line {line_number}")
        if tones > 0:
            try:
                float(average_tone)
            except ValueError as error:
                raise ValueError(
                    f"average tone is not numeric at CSV line {line_number}"
                ) from error

        total_documents += documents
        zero_document_rows += documents == 0

    missing = expected - observed
    if missing:
        sample = sorted(missing)[:3]
        raise ValueError(f"GDELT export is missing {len(missing)} rows; sample: {sample}")

    return {
        "complete": True,
        "period_start": start.isoformat(),
        "period_end_inclusive": end.isoformat(),
        "assets": list(ASSETS),
        "row_count": len(observed),
        "expected_row_count": len(expected),
        "rows_by_asset": dict(sorted(asset_rows.items())),
        "total_documents": total_documents,
        "zero_document_rows": zero_document_rows,
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate a bounded GDELT BigQuery CSV export and emit sanitized evidence"
    )
    parser.add_argument("csv", type=Path, help="local BigQuery CSV export")
    parser.add_argument(
        "--output",
        type=Path,
        help="optional local JSON evidence path; do not commit generated evidence",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    with args.csv.open(encoding="utf-8", newline="") as handle:
        evidence = validate_gdelt_csv(handle)
    evidence["csv_sha256"] = sha256_file(args.csv)
    rendered = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    print(rendered, end="")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
