from __future__ import annotations

import io
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from scripts.milestone0.gates import (
    GateResult,
    aggregate_status,
    audit_resvault,
    chunk_round_trip,
    scan_forbidden_persistence,
    sha256_file,
    validate_assets,
)
from scripts.milestone0.gdelt_evidence import validate_gdelt_csv
from scripts.milestone0.providers import summarize_coin_metrics_period
from scripts.milestone0.run import (
    ATTESTED_GATE_NAMES,
    load_attested_gates,
    load_provider_attestation,
)


class AssetBoundaryTests(unittest.TestCase):
    def test_exact_asset_universe_is_accepted(self) -> None:
        validate_assets(["BTC", "ETH", "SOL"])

    def test_fourth_asset_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            validate_assets(["BTC", "ETH", "SOL", "DOGE"])


class ChunkProtocolTests(unittest.TestCase):
    def test_round_trip_is_content_identical(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = chunk_round_trip(
                size_bytes=1024 * 1024 + 19,
                chunk_size=256 * 1024,
                directory=Path(directory),
            )
        self.assertTrue(result["identical"])
        self.assertEqual(result["chunk_count"], 5)
        self.assertEqual(result["source_sha256"], result["restored_sha256"])


class GateAggregationTests(unittest.TestCase):
    def test_fail_takes_precedence(self) -> None:
        results = [
            GateResult("a", "blocked", "", {}),
            GateResult("b", "fail", "", {}),
        ]
        self.assertEqual(aggregate_status(results), "fail")

    def test_blocked_takes_precedence_over_partial(self) -> None:
        results = [
            GateResult("a", "partial", "", {}),
            GateResult("b", "blocked", "", {}),
        ]
        self.assertEqual(aggregate_status(results), "blocked")


class SecurityAuditTests(unittest.TestCase):
    def test_private_key_page_bridge_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            upstream = Path(directory)
            public = upstream / "ecosystem/tools/resvault/public"
            pages = upstream / "ecosystem/tools/resvault/src/pages"
            public.mkdir(parents=True)
            pages.mkdir(parents=True)
            (public / "content.js").write_text(
                "window.postMessage({privateKey: response.privateKey}, '*')",
                encoding="utf-8",
            )
            (public / "background.js").write_text(
                "sendResponse({privateKey: decryptedPrivateKey});\n"
                "crypto.subtle.exportKey('jwk', keyMaterial);\n"
                "const value = {exportedKey: exportedKey};",
                encoding="utf-8",
            )
            (public / "manifest.json").write_text(
                '{"content_scripts":[{"matches": ["<all_urls>"]}]}',
                encoding="utf-8",
            )
            (pages / "Login.jsx").write_text(
                "chrome.storage.local.set({ password: loginValues.password });",
                encoding="utf-8",
            )
            result = audit_resvault(upstream)
        self.assertEqual(result.status, "fail")
        self.assertEqual(result.evidence["required_path"], "substantial-hardening")


class PersistencePolicyTests(unittest.TestCase):
    def test_forbidden_database_import_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            source = repo / "server/app"
            source.mkdir(parents=True)
            (source / "repository.py").write_text("import sqlite3\n", encoding="utf-8")
            result = scan_forbidden_persistence(repo)
        self.assertEqual(result.status, "fail")


class ProviderCoverageTests(unittest.TestCase):
    def test_complete_three_asset_daily_period_is_detected(self) -> None:
        body = {
            "data": [
                {"asset": asset, "time": day, "PriceUSD": "1.0"}
                for asset in ("btc", "eth", "sol")
                for day in (
                    "2020-04-10T00:00:00.000000000Z",
                    "2020-04-11T00:00:00.000000000Z",
                )
            ]
        }

        summary = summarize_coin_metrics_period(
            body, start=date(2020, 4, 10), end=date(2020, 4, 11)
        )

        self.assertTrue(summary["complete"])
        self.assertEqual(summary["row_count"], 6)

    def test_null_or_missing_asset_day_is_incomplete(self) -> None:
        body = {
            "data": [
                {"asset": "btc", "time": "2020-04-10T00:00:00Z", "PriceUSD": None},
                {"asset": "eth", "time": "2020-04-10T00:00:00Z", "PriceUSD": "1"},
            ]
        }

        summary = summarize_coin_metrics_period(
            body, start=date(2020, 4, 10), end=date(2020, 4, 10)
        )

        self.assertFalse(summary["complete"])

    def test_duplicate_row_cannot_hide_a_missing_day(self) -> None:
        body = {
            "data": [
                {"asset": "btc", "time": "2020-04-10T00:00:00Z", "PriceUSD": "1"},
                {"asset": "btc", "time": "2020-04-10T12:00:00Z", "PriceUSD": "1"},
                {"asset": "eth", "time": "2020-04-10T00:00:00Z", "PriceUSD": "1"},
                {"asset": "eth", "time": "2020-04-11T00:00:00Z", "PriceUSD": "1"},
                {"asset": "sol", "time": "2020-04-10T00:00:00Z", "PriceUSD": "1"},
                {"asset": "sol", "time": "2020-04-11T00:00:00Z", "PriceUSD": "1"},
            ]
        }

        summary = summarize_coin_metrics_period(
            body, start=date(2020, 4, 10), end=date(2020, 4, 11)
        )

        self.assertFalse(summary["complete"])
        btc = summary["assets"]["btc"]
        self.assertEqual(btc["duplicate_date_count"], 1)
        self.assertEqual(btc["missing_date_count"], 1)


class GdeltEvidenceTests(unittest.TestCase):
    HEADER = (
        "day,asset,document_count,source_count,tone_observation_count,average_tone,"
        "positive_document_count,negative_document_count,neutral_document_count\n"
    )

    def test_complete_daily_asset_grid_is_accepted(self) -> None:
        rows = [
            f"2020-04-10,{asset},1,1,1,0.5,1,0,0\n"
            for asset in ("BTC", "ETH", "SOL")
        ]
        evidence = validate_gdelt_csv(
            io.StringIO(self.HEADER + "".join(rows)),
            start=date(2020, 4, 10),
            end=date(2020, 4, 10),
        )

        self.assertTrue(evidence["complete"])
        self.assertEqual(evidence["row_count"], 3)
        self.assertEqual(evidence["total_documents"], 3)

    def test_missing_asset_day_is_rejected(self) -> None:
        rows = [
            "2020-04-10,BTC,0,0,0,,0,0,0\n",
            "2020-04-10,ETH,0,0,0,,0,0,0\n",
        ]
        with self.assertRaisesRegex(ValueError, "missing 1 rows"):
            validate_gdelt_csv(
                io.StringIO(self.HEADER + "".join(rows)),
                start=date(2020, 4, 10),
                end=date(2020, 4, 10),
            )

    def test_inconsistent_tone_counts_are_rejected(self) -> None:
        rows = [
            "2020-04-10,BTC,1,1,1,0.5,0,0,0\n",
            "2020-04-10,ETH,0,0,0,,0,0,0\n",
            "2020-04-10,SOL,0,0,0,,0,0,0\n",
        ]
        with self.assertRaisesRegex(ValueError, "tone counts are inconsistent"):
            validate_gdelt_csv(
                io.StringIO(self.HEADER + "".join(rows)),
                start=date(2020, 4, 10),
                end=date(2020, 4, 10),
            )


class LocalAttestationTests(unittest.TestCase):
    def _write_attestation(self, directory: str, *, status: str = "pass") -> Path:
        path = Path(directory) / "attestation.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "gates": [
                        {
                            "gate": gate,
                            "status": status,
                            "summary": "verified",
                            "evidence": {},
                        }
                        for gate in ATTESTED_GATE_NAMES
                    ],
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_exact_gate_set_and_valid_status_are_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, results = load_attested_gates(self._write_attestation(directory))

        self.assertEqual(tuple(result.gate for result in results), ATTESTED_GATE_NAMES)

    def test_unknown_status_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_attestation(directory, status="unknown")
            with self.assertRaisesRegex(ValueError, "invalid.*status"):
                load_attested_gates(path)

    def test_duplicate_or_missing_gate_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_attestation(directory)
            value = json.loads(path.read_text(encoding="utf-8"))
            value["gates"][-1]["gate"] = ATTESTED_GATE_NAMES[0]
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "exactly once"):
                load_attested_gates(path)


class ProviderAttestationTests(unittest.TestCase):
    def _write_attestation(self, directory: str, query_hash: str) -> Path:
        path = Path(directory) / "provider.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "pass",
                    "gdelt_bigquery": {
                        "query_sha256": query_hash,
                        "csv_sha256": "data-hash",
                        "row_count": 5184,
                        "rows_by_asset": {"BTC": 1728, "ETH": 1728, "SOL": 1728},
                        "billing_enabled": False,
                    },
                    "resilientdb_persistence": {
                        "identical": True,
                        "source_sha256": "data-hash",
                        "restored_sha256": "data-hash",
                    },
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_complete_billing_disabled_attestation_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            query = Path(directory) / "query.sql"
            query.write_text("SELECT 1", encoding="utf-8")
            attestation = self._write_attestation(directory, sha256_file(query))

            loaded = load_provider_attestation(attestation, query_path=query)

        self.assertEqual(loaded["status"], "pass")

    def test_modified_query_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            query = Path(directory) / "query.sql"
            query.write_text("SELECT 1", encoding="utf-8")
            attestation = self._write_attestation(directory, "stale-hash")
            with self.assertRaisesRegex(ValueError, "query digest"):
                load_provider_attestation(attestation, query_path=query)


if __name__ == "__main__":
    unittest.main()
