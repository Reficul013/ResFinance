from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Sequence
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


def _coin_metrics_url(
    start: str,
    end: str,
    *,
    assets: Sequence[str] = ("btc", "eth", "sol"),
    metrics: Sequence[str] = ("PriceUSD",),
    page_size: int = 100,
) -> str:
    query = urllib.parse.urlencode(
        {
            "assets": ",".join(assets),
            "metrics": ",".join(metrics),
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
    return summarize_coin_metrics_metrics_period(
        body,
        start=start,
        end=end,
        assets=("btc", "eth", "sol"),
        metrics=("PriceUSD",),
    )


def summarize_coin_metrics_metrics_period(
    body: object,
    *,
    start: date,
    end: date,
    assets: Sequence[str],
    metrics: Sequence[str],
) -> dict[str, object]:
    rows = body.get("data", []) if isinstance(body, dict) else []
    typed_rows = [row for row in rows if isinstance(row, dict)]
    expected_days = (end - start).days + 1
    expected_dates = {
        (start + timedelta(days=offset)).isoformat() for offset in range(expected_days)
    }
    by_asset: dict[str, dict[str, object]] = {}
    counts = Counter(str(row.get("asset")) for row in typed_rows)
    expected_assets = set(assets)
    for asset in assets:
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
            "null_counts": {
                metric: sum(row.get(metric) is None for row in asset_rows)
                for metric in metrics
            },
            "missing_metric_key_counts": {
                metric: sum(metric not in row for row in asset_rows) for metric in metrics
            },
            "complete": (
                counts[asset] == expected_days
                and unique_dates == expected_dates
                and len(actual_dates) == len(unique_dates)
                and all(
                    metric in row and row.get(metric) is not None
                    for row in asset_rows
                    for metric in metrics
                )
            ),
        }
    unexpected_asset_count = sum(
        count for asset, count in counts.items() if asset not in expected_assets
    )
    return {
        "row_count": len(typed_rows),
        "expected_row_count": expected_days * len(assets),
        "metrics": list(metrics),
        "unexpected_asset_count": unexpected_asset_count,
        "assets": by_asset,
        "complete": (
            len(typed_rows) == expected_days * len(assets)
            and unexpected_asset_count == 0
            and all(bool(item["complete"]) for item in by_asset.values())
        ),
        "next_page_url": body.get("next_page_url") if isinstance(body, dict) else None,
    }


def summarize_epoch_series_period(
    body: object,
    *,
    start: date,
    end: date,
    value_path: Sequence[str],
) -> dict[str, object]:
    rows = body if isinstance(body, list) else []
    expected_dates = {
        start + timedelta(days=offset) for offset in range((end - start).days + 1)
    }
    observations: list[tuple[date, object]] = []
    invalid_row_count = 0
    for row in rows:
        if not isinstance(row, dict):
            invalid_row_count += 1
            continue
        epoch = row.get("date")
        try:
            observed_date = datetime.fromtimestamp(int(str(epoch)), UTC).date()
        except (TypeError, ValueError, OSError, OverflowError):
            invalid_row_count += 1
            continue
        if observed_date not in expected_dates:
            continue
        value: object = row
        for key in value_path:
            if not isinstance(value, dict) or key not in value:
                value = None
                break
            value = value[key]
        observations.append((observed_date, value))

    dates = [item[0] for item in observations]
    unique_dates = set(dates)
    first_date = min(unique_dates) if unique_dates else None
    last_date = max(unique_dates) if unique_dates else None
    internal_expected = (
        {
            first_date + timedelta(days=offset)
            for offset in range((last_date - first_date).days + 1)
        }
        if first_date is not None and last_date is not None
        else set()
    )
    return {
        "period_row_count": len(observations),
        "expected_daily_rows": len(expected_dates),
        "first_date": first_date.isoformat() if first_date else None,
        "last_date": last_date.isoformat() if last_date else None,
        "pre_availability_mask_days": (
            (first_date - start).days if first_date is not None else len(expected_dates)
        ),
        "internal_missing_days": len(internal_expected - unique_dates),
        "post_availability_mask_days": (
            (end - last_date).days if last_date is not None else 0
        ),
        "total_missing_days": len(expected_dates - unique_dates),
        "duplicate_date_count": len(dates) - len(unique_dates),
        "null_value_count": sum(value is None for _, value in observations),
        "invalid_row_count": invalid_row_count,
        "ends_at_research_boundary": last_date == end,
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
        _coin_metrics_url(
            period_start.isoformat(),
            period_end.isoformat(),
            assets=("btc", "eth"),
            metrics=("AdrActCnt", "TxCnt"),
            page_size=10_000,
        )
    )
    metadata["coverage"] = summarize_coin_metrics_metrics_period(
        body,
        start=period_start,
        end=period_end,
        assets=("btc", "eth"),
        metrics=("AdrActCnt", "TxCnt"),
    )
    probes["coin_metrics_on_chain_full_period"] = metadata

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
    metadata["coverage"] = summarize_epoch_series_period(
        body,
        start=period_start,
        end=period_end,
        value_path=("tvl",),
    )
    probes["defillama_solana_tvl"] = metadata

    metadata, body = _request_json(
        "https://stablecoins.llama.fi/stablecoincharts/Solana"
    )
    metadata["coverage"] = summarize_epoch_series_period(
        body,
        start=period_start,
        end=period_end,
        value_path=("totalCirculatingUSD", "peggedUSD"),
    )
    probes["defillama_solana_stablecoin_supply"] = metadata

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
                "status": "pass-for-noncommercial-research-with-attribution",
                "finding": (
                    "Coin Metrics Community data is published under CC BY-NC 4.0. "
                    "ResFinance's current university research use must remain "
                    "non-commercial and provide attribution."
                ),
                "source": "https://github.com/coinmetrics/data",
            },
            "coingecko": {
                "status": "pass-for-current-display-with-attribution",
                "finding": (
                    "Use requires attribution; raw API access or data may not be "
                    "resold, redistributed, or syndicated without a separate agreement."
                ),
                "source": "https://www.coingecko.com/en/api_terms",
            },
            "defillama": {
                "status": "pass-for-declared-personal-noncommercial-research-only",
                "finding": (
                    "Current terms grant personal, non-commercial use and require "
                    "written consent for commercial harvesting. The declared personal "
                    "university research scope is non-commercial; institutional or "
                    "commercial reuse requires a new review."
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
