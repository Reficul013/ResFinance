from __future__ import annotations

import math
from dataclasses import dataclass
from typing import cast

import torch
from torch import Tensor

from ml.features.point_in_time import FeatureDataset
from server.app.domain.crypto import CryptoAsset

HORIZONS = (1, 3, 5, 7, 15)
SOURCE_NAMES = ("market", "sentiment", "on_chain")
SOURCE_WIDTH = 3
ASSETS = (CryptoAsset.BTC, CryptoAsset.ETH, CryptoAsset.SOL)


@dataclass(frozen=True)
class ResearchSequenceDataset:
    features: Tensor
    masks: Tensor
    targets: Tensor
    asset_indices: Tensor
    decision_dates: tuple[str, ...]
    assets: tuple[str, ...]
    dataset_hash: str
    source_record_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        sample_count = self.features.shape[0]
        if self.features.ndim != 4 or self.features.shape[2:] != (3, SOURCE_WIDTH):
            raise ValueError("features must have shape [sample, lookback, 3, 3]")
        if self.masks.shape != self.features.shape:
            raise ValueError("feature masks must match features")
        if self.targets.shape != (sample_count, len(HORIZONS)):
            raise ValueError("targets must cover all forecast horizons")
        if len(self.decision_dates) != sample_count or len(self.assets) != sample_count:
            raise ValueError("sample metadata length mismatch")
        if set(self.assets) != {asset.value for asset in ASSETS}:
            raise ValueError("research dataset must contain exactly BTC, ETH, and SOL")


@dataclass(frozen=True)
class InferenceBatch:
    features: Tensor
    masks: Tensor
    asset_indices: Tensor
    decision_time_utc: str
    assets: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.features.ndim != 4 or self.features.shape[0] != 3 or self.features.shape[2:] != (
            3,
            SOURCE_WIDTH,
        ):
            raise ValueError("inference features must contain BTC, ETH, and SOL")
        if self.masks.shape != self.features.shape:
            raise ValueError("inference masks must match features")
        if self.asset_indices.tolist() != [0, 1, 2]:
            raise ValueError("inference assets must use canonical BTC, ETH, SOL order")


@dataclass(frozen=True)
class MaskedStandardizer:
    means: Tensor
    scales: Tensor

    @classmethod
    def fit(cls, features: Tensor, masks: Tensor) -> MaskedStandardizer:
        if features.shape != masks.shape:
            raise ValueError("feature masks must match features")
        valid = masks.to(features.dtype)
        counts = valid.sum(dim=(0, 1)).clamp_min(1.0)
        means = (features * valid).sum(dim=(0, 1)) / counts
        variances = (((features - means) ** 2) * valid).sum(dim=(0, 1)) / counts
        return cls(means=means, scales=variances.sqrt().clamp_min(1e-6))

    def transform(self, features: Tensor, masks: Tensor) -> Tensor:
        return ((features - self.means) / self.scales) * masks.to(features.dtype)


def requires_market_only_fallback(masks: Tensor) -> Tensor:
    """Per sample: True when sentiment or on-chain data is unavailable at the decision row.

    The point-in-time builder masks a source once its newest value is older than the maximum
    source age, so a masked source at the last lookback step means it is missing or stale.
    """
    if masks.ndim != 4 or masks.shape[2:] != (len(SOURCE_NAMES), SOURCE_WIDTH):
        raise ValueError("masks must have shape [batch, lookback, source, width]")
    available = masks[:, -1, :, :].any(dim=-1)
    return ~available[:, 1:].all(dim=1)


def build_sequence_dataset(
    dataset: FeatureDataset,
    *,
    lookback: int = 16,
    horizons: tuple[int, ...] = HORIZONS,
) -> ResearchSequenceDataset:
    if horizons != HORIZONS:
        raise ValueError("Milestone 6 horizons must be 1, 3, 5, 7, and 15 days")
    if lookback < 8:
        raise ValueError("lookback must contain at least eight daily observations")
    manifest_assets = dataset.manifest.get("assets")
    if manifest_assets != [asset.value for asset in ASSETS]:
        raise ValueError("feature manifest must contain exactly BTC, ETH, and SOL")

    by_asset: dict[str, list[dict[str, object]]] = {asset.value: [] for asset in ASSETS}
    for row in dataset.rows:
        asset = CryptoAsset.parse(str(row["asset"])).value
        by_asset[asset].append(row)
    for rows in by_asset.values():
        rows.sort(key=lambda row: str(row["timestamp_utc"]))

    all_features: list[Tensor] = []
    all_masks: list[Tensor] = []
    all_targets: list[Tensor] = []
    asset_indices: list[int] = []
    decision_dates: list[str] = []
    sample_assets: list[str] = []
    max_horizon = max(horizons)
    for asset_index, asset in enumerate(ASSETS):
        rows = by_asset[asset.value]
        prices = [_required_price(row) for row in rows]
        encoded = [_encode_row(row) for row in rows]
        for target_index in range(lookback - 1, len(rows) - max_horizon):
            window = encoded[target_index - lookback + 1 : target_index + 1]
            all_features.append(torch.stack([item[0] for item in window]))
            all_masks.append(torch.stack([item[1] for item in window]))
            current_price = prices[target_index]
            all_targets.append(
                torch.tensor(
                    [prices[target_index + horizon] / current_price - 1.0 for horizon in horizons],
                    dtype=torch.float32,
                )
            )
            asset_indices.append(asset_index)
            decision_dates.append(str(rows[target_index]["timestamp_utc"]))
            sample_assets.append(asset.value)

    order = sorted(
        range(len(decision_dates)),
        key=lambda index: (decision_dates[index], sample_assets[index]),
    )
    source_ids = dataset.manifest.get("source_record_ids")
    if not isinstance(source_ids, list) or not all(isinstance(item, str) for item in source_ids):
        raise ValueError("feature manifest source_record_ids are invalid")
    return ResearchSequenceDataset(
        features=torch.stack([all_features[index] for index in order]),
        masks=torch.stack([all_masks[index] for index in order]),
        targets=torch.stack([all_targets[index] for index in order]),
        asset_indices=torch.tensor([asset_indices[index] for index in order], dtype=torch.long),
        decision_dates=tuple(decision_dates[index] for index in order),
        assets=tuple(sample_assets[index] for index in order),
        dataset_hash=dataset.dataset_hash,
        source_record_ids=tuple(cast(list[str], source_ids)),
    )


def build_inference_batch(dataset: FeatureDataset, *, lookback: int = 16) -> InferenceBatch:
    if lookback < 8:
        raise ValueError("lookback must contain at least eight daily observations")
    if dataset.manifest.get("assets") != [asset.value for asset in ASSETS]:
        raise ValueError("feature manifest must contain exactly BTC, ETH, and SOL")
    by_asset: dict[str, list[dict[str, object]]] = {asset.value: [] for asset in ASSETS}
    for row in dataset.rows:
        by_asset[CryptoAsset.parse(str(row["asset"])).value].append(row)
    windows: list[Tensor] = []
    masks: list[Tensor] = []
    decision_times: set[str] = set()
    for asset in ASSETS:
        rows = sorted(by_asset[asset.value], key=lambda row: str(row["timestamp_utc"]))
        if len(rows) < lookback:
            raise ValueError("inference dataset has insufficient history")
        window = rows[-lookback:]
        if any(_required_price(row) <= 0 for row in window):
            raise ValueError("inference window requires complete market prices")
        encoded = [_encode_row(row) for row in window]
        windows.append(torch.stack([item[0] for item in encoded]))
        masks.append(torch.stack([item[1] for item in encoded]))
        decision_times.add(str(window[-1]["decision_time_utc"]))
    if len(decision_times) != 1:
        raise ValueError("inference assets must share one point-in-time cutoff")
    return InferenceBatch(
        features=torch.stack(windows),
        masks=torch.stack(masks),
        asset_indices=torch.arange(3, dtype=torch.long),
        decision_time_utc=decision_times.pop(),
        assets=tuple(asset.value for asset in ASSETS),
    )


def _required_price(row: dict[str, object]) -> float:
    values = row.get("values")
    if not isinstance(values, dict) or values.get("market_price_usd") is None:
        raise ValueError("every research row requires a market price")
    price = float(str(values["market_price_usd"]))
    if not math.isfinite(price) or price <= 0:
        raise ValueError("market price must be positive and finite")
    return price


def _encode_row(row: dict[str, object]) -> tuple[Tensor, Tensor]:
    values = row.get("values")
    masks = row.get("availability_masks")
    if not isinstance(values, dict) or not isinstance(masks, dict):
        raise ValueError("feature row values and availability masks are required")
    price = _number(values, masks, "market_price_usd", log=True)
    market_return = _number(values, masks, "market_return_1d")
    tone = _number(values, masks, "sentiment_average_tone")
    documents = _number(values, masks, "sentiment_document_count", log=True)
    mentions = _number(values, masks, "sentiment_mention_count", log=True)
    active = _number(values, masks, "on_chain_active_addresses", log=True)
    transactions = _number(values, masks, "on_chain_transaction_count", log=True)
    tvl = _number(values, masks, "on_chain_solana_tvl_usd", log=True)
    stable = _number(values, masks, "on_chain_solana_stablecoin_supply_usd", log=True)
    on_chain_first = active if active[1] else tvl
    on_chain_second = transactions if transactions[1] else stable
    feature_values = torch.tensor(
        [
            [market_return[0], price[0], 0.0],
            [tone[0], documents[0], mentions[0]],
            [on_chain_first[0], on_chain_second[0], 0.0],
        ],
        dtype=torch.float32,
    )
    feature_masks = torch.tensor(
        [
            [market_return[1], price[1], False],
            [tone[1], documents[1], mentions[1]],
            [on_chain_first[1], on_chain_second[1], False],
        ],
        dtype=torch.bool,
    )
    return feature_values, feature_masks


def _number(
    values: dict[object, object],
    masks: dict[object, object],
    name: str,
    *,
    log: bool = False,
) -> tuple[float, bool]:
    available = masks.get(name) is True and values.get(name) is not None
    if not available:
        return 0.0, False
    parsed = float(str(values[name]))
    if not math.isfinite(parsed):
        raise ValueError(f"feature {name} must be finite")
    if log:
        if parsed < 0:
            raise ValueError(f"feature {name} cannot be negative for log scaling")
        parsed = math.log1p(parsed)
    return parsed, True
