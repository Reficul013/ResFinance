from __future__ import annotations

from enum import StrEnum
from typing import NamedTuple, cast

import torch
from torch import Tensor, nn
from torch.nn import functional as F

from ml.data.datasets import HORIZONS, SOURCE_NAMES, SOURCE_WIDTH


class FusionMode(StrEnum):
    ADAPTIVE = "adaptive-gating"
    FIXED_EQUAL = "fixed-equal-fusion"
    MARKET_ONLY = "market-only"
    WITHOUT_MARKET = "without-market"
    WITHOUT_SENTIMENT = "without-sentiment"
    WITHOUT_ON_CHAIN = "without-on-chain"


class ModelOutput(NamedTuple):
    expected_return: Tensor
    direction_logits: Tensor
    quantiles: Tensor
    gate_weights: Tensor


class SourceEncoder(nn.Module):
    def __init__(self, width: int, dimension: int) -> None:
        super().__init__()
        self.network = nn.Sequential(
            nn.Linear(width, dimension),
            nn.GELU(),
            nn.LayerNorm(dimension),
        )

    def forward(self, values: Tensor, masks: Tensor) -> Tensor:
        encoded = self.network(values * masks.to(values.dtype))
        present = masks.any(dim=-1, keepdim=True)
        return torch.mul(encoded, present.to(encoded.dtype))


class ChannelIndependentPatchScale(nn.Module):
    """Patch each latent channel independently, then share one Transformer across channels."""

    def __init__(self, *, patch_size: int, latent_channels: int, model_dimension: int) -> None:
        super().__init__()
        self.patch_size = patch_size
        self.projection = nn.Linear(patch_size, model_dimension)
        layer = nn.TransformerEncoderLayer(
            d_model=model_dimension,
            nhead=2,
            dim_feedforward=model_dimension * 2,
            dropout=0.0,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.transformer = nn.TransformerEncoder(
            layer, num_layers=1, enable_nested_tensor=False
        )
        self.channel_count = latent_channels

    def forward(self, fused: Tensor) -> Tensor:
        batch, steps, channels = fused.shape
        if channels != self.channel_count:
            raise ValueError("unexpected latent channel count")
        channel_series = fused.transpose(1, 2)
        remainder = steps % self.patch_size
        if remainder:
            channel_series = F.pad(channel_series, (self.patch_size - remainder, 0))
        patches = channel_series.unfold(dimension=2, size=self.patch_size, step=self.patch_size)
        patch_count = patches.shape[2]
        tokens = self.projection(patches).reshape(
            batch * channels, patch_count, self.projection.out_features
        )
        encoded = cast(Tensor, self.transformer(tokens)).mean(dim=1)
        return encoded.reshape(batch, channels, self.projection.out_features)


class ForecastHeads(nn.Module):
    def __init__(self, dimension: int, horizon_count: int = len(HORIZONS)) -> None:
        super().__init__()
        self.horizon_count = horizon_count
        self.expected = nn.Linear(dimension, horizon_count)
        self.direction = nn.Linear(dimension, horizon_count)
        self.quantile_parameters = nn.Linear(dimension, horizon_count * 3)

    def forward(self, representation: Tensor, gate_weights: Tensor) -> ModelOutput:
        expected = 0.1 * torch.tanh(self.expected(representation))
        direction = self.direction(representation)
        raw = self.quantile_parameters(representation).reshape(
            representation.shape[0], self.horizon_count, 3
        )
        median = 0.1 * torch.tanh(raw[:, :, 1])
        lower = median - 0.1 * F.softplus(raw[:, :, 0])
        upper = median + 0.1 * F.softplus(raw[:, :, 2])
        return ModelOutput(
            expected,
            direction,
            torch.stack((lower, median, upper), dim=-1),
            gate_weights,
        )


class ThreeAssetMSPCIFormer(nn.Module):
    """Clean-room three-asset adaptation of the documented MSPCIFormer method."""

    def __init__(
        self,
        *,
        fusion_mode: FusionMode = FusionMode.ADAPTIVE,
        source_dimension: int = 6,
        model_dimension: int = 8,
        patch_sizes: tuple[int, ...] = (2, 4, 8),
        horizon_count: int = len(HORIZONS),
    ) -> None:
        super().__init__()
        if not patch_sizes or any(size <= 0 for size in patch_sizes):
            raise ValueError("patch sizes must be positive")
        self.fusion_mode = fusion_mode
        self.source_encoders = nn.ModuleList(
            SourceEncoder(SOURCE_WIDTH, source_dimension) for _ in SOURCE_NAMES
        )
        self.gate_score = nn.Linear(source_dimension, 1)
        self.patch_scales = nn.ModuleList(
            ChannelIndependentPatchScale(
                patch_size=size,
                latent_channels=source_dimension,
                model_dimension=model_dimension,
            )
            for size in patch_sizes
        )
        self.scale_logits = nn.Parameter(torch.zeros(len(patch_sizes)))
        self.asset_embedding = nn.Embedding(3, model_dimension)
        self.heads = ForecastHeads(model_dimension, horizon_count)

    def forward(self, features: Tensor, masks: Tensor, asset_indices: Tensor) -> ModelOutput:
        if features.ndim != 4 or features.shape[2:] != (len(SOURCE_NAMES), SOURCE_WIDTH):
            raise ValueError("features must have shape [batch, lookback, source, width]")
        encoded = torch.stack(
            [
                encoder(features[:, :, index, :], masks[:, :, index, :])
                for index, encoder in enumerate(self.source_encoders)
            ],
            dim=2,
        )
        source_present = masks.any(dim=-1)
        allowed = self._allowed_sources(features.device).reshape(1, 1, -1)
        available = source_present & allowed
        any_available = available.any(dim=2, keepdim=True)
        if self.fusion_mode is FusionMode.FIXED_EQUAL:
            raw_weights = available.to(features.dtype)
            gate_weights = raw_weights / raw_weights.sum(dim=2, keepdim=True).clamp_min(1.0)
        else:
            scores = self.gate_score(encoded).squeeze(-1)
            scores = scores.masked_fill(~available, float("-inf"))
            scores = torch.where(any_available, scores, torch.zeros_like(scores))
            gate_weights = torch.softmax(scores, dim=2)
            gate_weights = gate_weights * any_available.to(gate_weights.dtype)
        fused = (encoded * gate_weights.unsqueeze(-1)).sum(dim=2)
        scale_outputs = torch.stack([scale(fused) for scale in self.patch_scales], dim=1)
        scale_weights = torch.softmax(self.scale_logits, dim=0).reshape(1, -1, 1, 1)
        representation = (scale_outputs * scale_weights).sum(dim=1).mean(dim=1)
        representation = representation + self.asset_embedding(asset_indices)
        return cast(ModelOutput, self.heads(representation, gate_weights))

    def _allowed_sources(self, device: torch.device) -> Tensor:
        allowed = torch.ones(len(SOURCE_NAMES), dtype=torch.bool, device=device)
        excluded = {
            FusionMode.MARKET_ONLY: (1, 2),
            FusionMode.WITHOUT_MARKET: (0,),
            FusionMode.WITHOUT_SENTIMENT: (1,),
            FusionMode.WITHOUT_ON_CHAIN: (2,),
        }.get(self.fusion_mode, ())
        for index in excluded:
            allowed[index] = False
        return allowed


class LSTMForecastBaseline(nn.Module):
    def __init__(self, *, hidden_dimension: int = 12, horizon_count: int = len(HORIZONS)) -> None:
        super().__init__()
        input_dimension = len(SOURCE_NAMES) * SOURCE_WIDTH * 2
        self.lstm = nn.LSTM(input_dimension, hidden_dimension, batch_first=True)
        self.asset_embedding = nn.Embedding(3, hidden_dimension)
        self.heads = ForecastHeads(hidden_dimension, horizon_count)

    def forward(self, features: Tensor, masks: Tensor, asset_indices: Tensor) -> ModelOutput:
        values = torch.cat((features, masks.to(features.dtype)), dim=-1)
        flattened = values.reshape(values.shape[0], values.shape[1], -1)
        sequence, _ = cast(tuple[Tensor, tuple[Tensor, Tensor]], self.lstm(flattened))
        representation = sequence[:, -1, :] + self.asset_embedding(asset_indices)
        source_present = masks.any(dim=-1).to(features.dtype)
        weights = source_present / source_present.sum(dim=2, keepdim=True).clamp_min(1.0)
        return cast(ModelOutput, self.heads(representation, weights))
