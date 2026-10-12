from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import UTC, date, datetime, timedelta
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


def _coin_metrics_url(start: str, end: str, *, page_size: int = 100) -> str:
    query = urllib.parse.urlencode(
        {
            "assets": "btc,eth,sol",
            "metrics": "PriceUSD",
            "frequency": "1d",
            "start_time": start,
            "end_time": end,
            "page_size": str(page_size),
        }
    )
    return f"https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?{query}"


def summarize_coin_metrics_period(
    body: object, *, start: date, end: date
) -> dict[str, object]:
    rows = body.get("data", []) if isinstance(body, dict) else []
    typed_rows = [row for row in rows if isinstance(row, dict)]
    expected_days = (end - start).days + 1
    expected_dates = {
        (start + timedelta(days=offset)).isoformat() for offset in range(expected_days)
    }
    by_asset: dict[str, dict[str, object]] = {}
    counts = Counter(str(row.get("asset")) for row in typed_rows)
    for asset in ("btc", "eth", "sol"):
        asset_rows = [row for row in typed_rows if row.get("asset") == asset]
        times = sorted(str(row.get("time")) for row in asset_rows)
        actual_dates = [timestamp[:10] for timestamp in times]
        unique_dates = set(actual_dates)
        by_asset[asset] = {
            "row_count": counts[asset],
            "expected_daily_rows": expected_days,
            "first_time": times[0] if times else None,
            "last_time": times[-1] if times else None,
            "duplicate_date_count": len(actual_dates) - len(unique_dates),
            "missing_date_count": len(expected_dates - unique_dates),
            "unexpected_date_count": len(unique_dates - expected_dates),
            "null_price_count": sum(row.get("PriceUSD") is None for row in asset_rows),
            "complete": (
                counts[asset] == expected_days
                and unique_dates == expected_dates
                and len(actual_dates) == len(unique_dates)
                and all(row.get("PriceUSD") is not None for row in asset_rows)
            ),
        }
    unexpected_asset_count = sum(
        count for asset, count in counts.items() if asset not in {"btc", "eth", "sol"}
    )
    return {
        "row_count": len(typed_rows),
        "expected_row_count": expected_days * 3,
        "unexpected_asset_count": unexpected_asset_count,
        "assets": by_asset,
        "complete": (
            len(typed_rows) == expected_days * 3
            and unexpected_asset_count == 0
            and all(bool(item["complete"]) for item in by_asset.values())
        ),
        "next_page_url": body.get("next_page_url") if isinstance(body, dict) else None,
    }


def probe_providers() -> dict[str, object]:
    probes: dict[str, object] = {}

    period_start = date(2020, 4, 10)
    period_end = date(2025, 1, 1)
    metadata, body = _request_json(
        _coin_metrics_url(
            period_start.isoformat(), period_end.isoformat(), page_size=10_000
        )
    )
    metadata["coverage"] = summarize_coin_metrics_period(
        body, start=period_start, end=period_end
    )
    probes["coin_metrics_full_period"] = metadata

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
        epoch
        for row in rows
        if isinstance(row, dict) and isinstance((epoch := row.get("date")), int)
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
        "terms_review": {
            "coin_metrics": {
                "status": "needs-license-variant-confirmation",
                "finding": (
                    "Community data is offered under a Creative Commons license, "
                    "but the reviewed page does not identify the exact CC variant."
                ),
                "source": "https://gitbook-docs.coinmetrics.io/packages/coin-metrics-community-data",
            },
            "coingecko": {
                "status": "conditional",
                "finding": (
                    "Use requires attribution; raw API access or data may not be "
                    "resold, redistributed, or syndicated without a separate agreement."
                ),
                "source": "https://www.coingecko.com/en/api_terms",
            },
            "defillama": {
                "status": "blocked-for-commercial-use",
                "finding": (
                    "Current terms grant ordinary access for personal non-commercial "
                    "use and require prior written consent for commercial harvesting."
                ),
                "source": "https://enterprise.defillama.com/terms",
            },
            "gdelt": {
                "status": "pass-with-attribution",
                "finding": (
                    "Datasets permit unrestricted academic, commercial, and government "
                    "use and redistribution with GDELT citation and link."
                ),
                "source": "https://www.gdeltproject.org/about.html#termsofuse",
            },
        },
        "note": (
            "This is an engineering review, not legal advice. A conditional or blocked "
            "finding is not approved for production ingestion."
        ),
    }
