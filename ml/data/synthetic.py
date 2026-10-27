from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from ml.features.point_in_time import FEATURE_SCHEMA, FeatureDataset
from server.app.domain.crypto import CryptoAsset

ASSETS = (CryptoAsset.BTC, CryptoAsset.ETH, CryptoAsset.SOL)


def generate_synthetic_feature_dataset(
    *, day_count: int = 128, start: date = date(2024, 1, 1)
) -> FeatureDataset:
    """Create deterministic, non-provider smoke data without writing generated data to Git."""
    if day_count < 120:
        raise ValueError("synthetic smoke data requires at least 120 days")
    rows: list[dict[str, object]] = []
    source_ids: set[str] = set()
    prices = {CryptoAsset.BTC: 40_000.0, CryptoAsset.ETH: 2_200.0, CryptoAsset.SOL: 90.0}
    multipliers = {CryptoAsset.BTC: 1.0, CryptoAsset.ETH: 1.35, CryptoAsset.SOL: 1.8}

    for offset in range(day_count):
        current = start + timedelta(days=offset)
        for asset_index, asset in enumerate(ASSETS):
            cycle = math.sin((offset + asset_index * 2) / 6.0)
            trend = 0.0012 * multipliers[asset]
            daily_return = trend + 0.006 * cycle + 0.0015 * math.cos(offset / 3.0)
            previous_price = prices[asset]
            price = previous_price * (1.0 + daily_return)
            prices[asset] = price
            sentiment_available = (offset + asset_index) % 11 != 0
            on_chain_available = not (
                asset is CryptoAsset.SOL and offset < 24
            ) and (offset + asset_index) % 13 != 0
            values: dict[str, str | None] = {name: None for name in FEATURE_SCHEMA}
            masks = {name: False for name in FEATURE_SCHEMA}
            values["market_price_usd"] = _decimal(price)
            values["market_return_1d"] = _decimal(daily_return) if offset else None
            masks["market_price_usd"] = True
            masks["market_return_1d"] = offset > 0
            if sentiment_available:
                values["sentiment_average_tone"] = _decimal(cycle * 3.5)
                values["sentiment_document_count"] = str(80 + (offset * 7 + asset_index) % 31)
                values["sentiment_mention_count"] = str(120 + (offset * 11 + asset_index) % 47)
                masks["sentiment_average_tone"] = True
                masks["sentiment_document_count"] = True
                masks["sentiment_mention_count"] = True
            if on_chain_available:
                if asset in (CryptoAsset.BTC, CryptoAsset.ETH):
                    values["on_chain_active_addresses"] = str(
                        500_000 + asset_index * 90_000 + offset * 1_250
                    )
                    values["on_chain_transaction_count"] = str(
                        250_000 + asset_index * 60_000 + offset * 700
                    )
                    masks["on_chain_active_addresses"] = True
                    masks["on_chain_transaction_count"] = True
                else:
                    values["on_chain_solana_tvl_usd"] = _decimal(2_500_000_000 + offset * 8_000_000)
                    values["on_chain_solana_stablecoin_supply_usd"] = _decimal(
                        1_100_000_000 + offset * 4_000_000
                    )
                    masks["on_chain_solana_tvl_usd"] = True
                    masks["on_chain_solana_stablecoin_supply_usd"] = True
            timestamp = datetime.combine(current, datetime.min.time(), tzinfo=UTC)
            record_id = hashlib.sha256(
                f"m6:{asset.value}:{current.isoformat()}".encode()
            ).hexdigest()
            source_ids.add(record_id)
            row_core: dict[str, object] = {
                "schema_version": 1,
                "asset": asset.value,
                "timestamp_utc": timestamp.isoformat().replace("+00:00", "Z"),
                "decision_time_utc": (timestamp + timedelta(days=1)).isoformat().replace(
                    "+00:00", "Z"
                ),
                "values": values,
                "availability_masks": masks,
                "source_masks": {
                    "market": True,
                    "sentiment": sentiment_available,
                    "on_chain": on_chain_available,
                },
                "source_record_ids": {"synthetic": record_id},
            }
            rows.append({**row_core, "row_sha256": _hash(row_core)})

    manifest_core: dict[str, object] = {
        "schema_version": 1,
        "feature_schema": list(FEATURE_SCHEMA),
        "assets": [asset.value for asset in ASSETS],
        "providers": ["milestone6-deterministic-generator"],
        "start_date": start.isoformat(),
        "end_date_inclusive": (start + timedelta(days=day_count - 1)).isoformat(),
        "as_of_utc": "2026-10-14T00:00:00Z",
        "decision_lag_seconds": 86400,
        "row_count": len(rows),
        "source_record_ids": sorted(source_ids),
        "rows_sha256": _hash(rows),
        "generator": "resfinance-milestone6-v1",
    }
    dataset_hash = _hash(manifest_core)
    return FeatureDataset(
        dataset_hash,
        tuple(rows),
        {**manifest_core, "dataset_hash": dataset_hash},
    )


def _decimal(value: float | int) -> str:
    parsed = Decimal(str(value)).quantize(Decimal("0.0000000001"))
    return format(parsed.normalize(), "f")


def _hash(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode()).hexdigest()
