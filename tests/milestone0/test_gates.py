from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.milestone0.gates import (
    GateResult,
    aggregate_status,
    audit_resvault,
    chunk_round_trip,
    scan_forbidden_persistence,
    validate_assets,
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


if __name__ == "__main__":
    unittest.main()
