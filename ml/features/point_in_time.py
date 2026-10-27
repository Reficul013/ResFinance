from __future__ import annotations

import hashlib
import json
from bisect import bisect_right
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from server.app.domain.crypto import CryptoAsset, ObservationChannel, ProviderObservation

FEATURE_SCHEMA = (
    "market_price_usd",
    "market_return_1d",
    "sentiment_average_tone",
    "sentiment_document_count",
    "sentiment_positive_document_count",
    "sentiment_negative_document_count",
    "on_chain_active_addresses",
    "on_chain_transaction_count",
    "on_chain_solana_tvl_usd",
    "on_chain_solana_stablecoin_supply_usd",
)

METRIC_TO_FEATURE = {
    (ObservationChannel.MARKET, "price_usd"): "market_price_usd",
    (ObservationChannel.SENTIMENT, "average_tone"): "sentiment_average_tone",
    (ObservationChannel.SENTIMENT, "document_count"): "sentiment_document_count",
    (
        ObservationChannel.SENTIMENT,
        "positive_document_count",
    ): "sentiment_positive_document_count",
    (
        ObservationChannel.SENTIMENT,
        "negative_document_count",
    ): "sentiment_negative_document_count",
    (ObservationChannel.ON_CHAIN, "active_addresses"): "on_chain_active_addresses",
    (ObservationChannel.ON_CHAIN, "transaction_count"): "on_chain_transaction_count",
    (ObservationChannel.ON_CHAIN, "solana_tvl_usd"): "on_chain_solana_tvl_usd",
    (
        ObservationChannel.ON_CHAIN,
        "solana_stablecoin_supply_usd",
    ): "on_chain_solana_stablecoin_supply_usd",
}


# Non-market sources publish on their own delay (GDELT aggregates are available two days after
# the day they describe), so each row uses the latest observation already available at its
# decision time instead of requiring an observation for the row's own calendar day.
DEFAULT_MAX_SOURCE_AGE = timedelta(days=3)
_AGE_LOOKBACK_DAYS = 400


@dataclass(frozen=True)
class FeatureDataset:
    dataset_hash: str
    rows: tuple[dict[str, object], ...]
    manifest: dict[str, object]


class PointInTimeFeatureBuilder:
    def build(
        self,
        observations: Sequence[ProviderObservation],
        *,
        assets: Sequence[CryptoAsset | str],
        providers: Sequence[str],
        start: date,
        end: date,
        as_of_utc: datetime,
        decision_lag: timedelta = timedelta(days=1),
        max_source_age: timedelta = DEFAULT_MAX_SOURCE_AGE,
    ) -> FeatureDataset:
        if end < start:
            raise ValueError("feature period end cannot precede start")
        if max_source_age < timedelta(0):
            raise ValueError("maximum source age cannot be negative")
        as_of = _utc(as_of_utc)
        parsed_assets = tuple(
            asset if isinstance(asset, CryptoAsset) else CryptoAsset.parse(asset)
            for asset in assets
        )
        if not parsed_assets or len(set(parsed_assets)) != len(parsed_assets):
            raise ValueError("feature assets must be a non-empty unique sequence")
        provider_set = set(providers)
        if not provider_set or len(provider_set) != len(providers):
            raise ValueError("feature providers must be a non-empty unique sequence")

        indexed: dict[
            tuple[CryptoAsset, date, ObservationChannel, str],
            list[ProviderObservation],
        ] = defaultdict(list)
        for observation in observations:
            if (
                observation.asset not in set(parsed_assets)
                or observation.provider not in provider_set
            ):
                continue
            mapped = METRIC_TO_FEATURE.get((observation.channel, observation.metric))
            if mapped is None:
                continue
            indexed[
                (
                    observation.asset,
                    observation.observed_at_utc.date(),
                    observation.channel,
                    observation.metric,
                )
            ].append(observation)
        observed_days: dict[tuple[CryptoAsset, ObservationChannel, str], list[date]] = defaultdict(
            list
        )
        for asset_key, day, channel_key, metric_key in sorted(
            indexed, key=lambda key: (key[0].value, key[2].value, key[3], key[1])
        ):
            observed_days[(asset_key, channel_key, metric_key)].append(day)

        rows: list[dict[str, object]] = []
        record_ids: set[str] = set()
        previous_prices: dict[CryptoAsset, tuple[date, Decimal, str]] = {}
        current = start
        while current <= end:
            decision_time = min(
                as_of,
                datetime.combine(current, time.min, tzinfo=UTC) + decision_lag,
            )
            for asset in parsed_assets:
                values: dict[str, str | None] = {name: None for name in FEATURE_SCHEMA}
                masks = {name: False for name in FEATURE_SCHEMA}
                ages: dict[str, float | None] = {
                    feature: None for feature in METRIC_TO_FEATURE.values()
                }
                provenance: dict[str, str] = {}
                for (channel, metric), feature in METRIC_TO_FEATURE.items():
                    if channel is ObservationChannel.MARKET:
                        # Prices stay strictly same-day so returns never bridge a gap.
                        selected = _select_point_in_time(
                            indexed.get((asset, current, channel, metric), []), decision_time
                        )
                    else:
                        selected = _latest_available(
                            indexed,
                            observed_days.get((asset, channel, metric), []),
                            (asset, channel, metric),
                            current,
                            decision_time,
                        )
                    if selected is None:
                        continue
                    age = decision_time - selected.available_at_utc
                    ages[feature] = round(age.total_seconds() / 86_400, 6)
                    if channel is not ObservationChannel.MARKET and age > max_source_age:
                        continue
                    record_ids.add(selected.record_id)
                    provenance[feature] = selected.record_id
                    if not selected.missing:
                        values[feature] = selected.decimal_value
                        masks[feature] = True

                price_value = values["market_price_usd"]
                if price_value is not None:
                    price = Decimal(price_value)
                    previous = previous_prices.get(asset)
                    price_record_id = provenance["market_price_usd"]
                    if (
                        previous is not None
                        and previous[0] == current - timedelta(days=1)
                        and previous[1] != 0
                    ):
                        values["market_return_1d"] = _decimal_text(price / previous[1] - 1)
                        masks["market_return_1d"] = True
                        provenance["market_return_1d_previous"] = previous[2]
                    previous_prices[asset] = (current, price, price_record_id)

                source_masks = {
                    "market": masks["market_price_usd"],
                    "sentiment": any(
                        masks[name] for name in FEATURE_SCHEMA if name.startswith("sentiment_")
                    ),
                    "on_chain": any(
                        masks[name] for name in FEATURE_SCHEMA if name.startswith("on_chain_")
                    ),
                }
                row_core: dict[str, object] = {
                    "schema_version": 1,
                    "asset": asset.value,
                    "timestamp_utc": datetime.combine(current, time.min, tzinfo=UTC)
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "decision_time_utc": decision_time.isoformat().replace("+00:00", "Z"),
                    "values": values,
                    "availability_masks": masks,
                    "feature_age_days": dict(sorted(ages.items())),
                    "source_masks": source_masks,
                    "source_record_ids": dict(sorted(provenance.items())),
                }
                rows.append(
                    {
                        **row_core,
                        "row_sha256": hashlib.sha256(_canonical_json(row_core)).hexdigest(),
                    }
                )
            current += timedelta(days=1)

        manifest_core: dict[str, object] = {
            "schema_version": 1,
            "feature_schema": list(FEATURE_SCHEMA),
            "assets": [asset.value for asset in parsed_assets],
            "providers": sorted(provider_set),
            "start_date": start.isoformat(),
            "end_date_inclusive": end.isoformat(),
            "as_of_utc": as_of.isoformat().replace("+00:00", "Z"),
            "decision_lag_seconds": int(decision_lag.total_seconds()),
            "source_alignment": "latest-available-observation",
            "max_source_age_seconds": int(max_source_age.total_seconds()),
            "row_count": len(rows),
            "source_record_ids": sorted(record_ids),
            "rows_sha256": hashlib.sha256(_canonical_json(rows)).hexdigest(),
        }
        dataset_hash = hashlib.sha256(_canonical_json(manifest_core)).hexdigest()
        manifest = {**manifest_core, "dataset_hash": dataset_hash}
        return FeatureDataset(dataset_hash, tuple(rows), manifest)


def _latest_available(
    indexed: dict[tuple[CryptoAsset, date, ObservationChannel, str], list[ProviderObservation]],
    days: Sequence[date],
    key: tuple[CryptoAsset, ObservationChannel, str],
    current: date,
    cutoff: datetime,
) -> ProviderObservation | None:
    """Newest observation describing ``current`` or earlier that is available by ``cutoff``."""
    asset, channel, metric = key
    earliest = current - timedelta(days=_AGE_LOOKBACK_DAYS)
    for position in range(bisect_right(days, current) - 1, -1, -1):
        day = days[position]
        if day < earliest:
            return None
        selected = _select_point_in_time(indexed[(asset, day, channel, metric)], cutoff)
        if selected is not None:
            return selected
    return None


def _select_point_in_time(
    observations: Sequence[ProviderObservation], cutoff: datetime
) -> ProviderObservation | None:
    available = [item for item in observations if item.available_at_utc <= cutoff]
    if not available:
        return None
    return max(
        available,
        key=lambda item: (
            item.available_at_utc,
            item.retrieved_at_utc,
            item.provider_revision,
            item.record_id,
        ),
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("as_of_utc must be timezone-aware")
    return value.astimezone(UTC)


def _decimal_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )
