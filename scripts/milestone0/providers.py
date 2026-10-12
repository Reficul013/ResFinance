from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from typing import Any


def _request_json(url: str) -> tuple[dict[str, object], Any | None]:
    started = time.monotonic()
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "ResFinance-Milestone0/1.0"},
    )
    retrieved = datetime.now(UTC).isoformat()
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read()
            metadata: dict[str, object] = {
                "url": url,
                "http_status": response.status,
                "retrieved_at_utc": retrieved,
                "elapsed_ms": round((time.monotonic() - started) * 1000),
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "content_type": response.headers.get("Content-Type", ""),
            }
            try:
                return metadata, json.loads(payload)
            except json.JSONDecodeError as error:
                metadata["error"] = f"invalid JSON response: {error}"
                return metadata, None
    except urllib.error.HTTPError as error:
        return (
            {
                "url": url,
                "http_status": error.code,
                "retrieved_at_utc": retrieved,
                "elapsed_ms": round((time.monotonic() - started) * 1000),
                "error": error.reason,
            },
            None,
        )
    except (urllib.error.URLError, TimeoutError) as error:
        return (
            {
                "url": url,
                "http_status": None,
                "retrieved_at_utc": retrieved,
                "elapsed_ms": round((time.monotonic() - started) * 1000),
                "error": str(error),
            },
            None,
        )


def _coin_metrics_url(start: str, end: str) -> str:
    query = urllib.parse.urlencode(
        {
            "assets": "btc,eth,sol",
            "metrics": "PriceUSD",
            "frequency": "1d",
            "start_time": start,
            "end_time": end,
            "page_size": "100",
        }
    )
    return f"https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?{query}"


def probe_providers() -> dict[str, object]:
    probes: dict[str, object] = {}

    for name, start, end in (
        ("coin_metrics_start", "2020-04-10", "2020-04-12"),
        ("coin_metrics_end", "2024-12-30", "2025-01-01"),
    ):
        metadata, body = _request_json(_coin_metrics_url(start, end))
        rows = body.get("data", []) if isinstance(body, dict) else []
        typed_rows = [row for row in rows if isinstance(row, dict)]
        metadata["row_count"] = len(rows)
        metadata["assets"] = sorted(
            {
                str(asset)
                for row in typed_rows
                if isinstance((asset := row.get("asset")), str)
            }
        )
        metadata["times"] = sorted(
            {
                str(timestamp)
                for row in typed_rows
                if isinstance((timestamp := row.get("time")), str)
            }
        )
        probes[name] = metadata

    metadata, body = _request_json(
        "https://api.coingecko.com/api/v3/simple/price?"
        "ids=bitcoin%2Cethereum%2Csolana&vs_currencies=usd"
    )
    metadata["assets"] = sorted(str(asset) for asset in body) if isinstance(body, dict) else []
    probes["coingecko_current"] = metadata

    metadata, body = _request_json(
        "https://api.llama.fi/v2/historicalChainTvl/Solana"
    )
    rows = body if isinstance(body, list) else []
    dates = [
        date
        for row in rows
        if isinstance(row, dict) and isinstance((date := row.get("date")), int)
    ]
    metadata["row_count"] = len(rows)
    metadata["first_epoch"] = min(dates) if dates else None
    metadata["last_epoch"] = max(dates) if dates else None
    probes["defillama_solana_tvl"] = metadata

    gdelt_query = urllib.parse.urlencode(
        {
            "query": "bitcoin OR ethereum OR solana",
            "mode": "timelinevolraw",
            "format": "json",
            "maxrecords": "1",
            "startdatetime": "20200101000000",
            "enddatetime": "20200102000000",
        }
    )
    metadata, body = _request_json(
        f"https://api.gdeltproject.org/api/v2/doc/doc?{gdelt_query}"
    )
    metadata["json_received"] = body is not None
    probes["gdelt_doc"] = metadata

    return {
        "probes": probes,
        "license_references": {
            "coin_metrics": "https://docs.coinmetrics.io/api/v4/",
            "coingecko": "https://www.coingecko.com/en/terms",
            "defillama": "https://defillama.com/terms",
            "gdelt": "https://www.gdeltproject.org/about.html#termsofuse",
        },
        "note": (
            "Endpoint response is not license approval. Terms and redistribution "
            "requirements require explicit review before ingestion."
        ),
    }
