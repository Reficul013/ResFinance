from __future__ import annotations

import torch

from ml.data.datasets import requires_market_only_fallback
from ml.models.mspciformer import FusionMode, LSTMForecastBaseline, ThreeAssetMSPCIFormer


def inputs() -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    torch.manual_seed(9)
    features = torch.randn(6, 16, 3, 3)
    masks = torch.ones_like(features, dtype=torch.bool)
    masks[0, :4, 2, :] = False
    assets = torch.tensor((0, 1, 2, 0, 1, 2), dtype=torch.long)
    return features, masks, assets


def test_mspciformer_outputs_all_horizons_ordered_quantiles_and_masked_gates() -> None:
    features, masks, assets = inputs()
    model = ThreeAssetMSPCIFormer(fusion_mode=FusionMode.ADAPTIVE)

    output = model(features, masks, assets)

    assert output.expected_return.shape == (6, 5)
    assert output.direction_logits.shape == (6, 5)
    assert output.quantiles.shape == (6, 5, 3)
    assert torch.all(output.quantiles[:, :, 0] <= output.quantiles[:, :, 1])
    assert torch.all(output.quantiles[:, :, 1] <= output.quantiles[:, :, 2])
    assert torch.all(output.gate_weights[0, :4, 2] == 0)


def test_every_required_fusion_ablation_executes() -> None:
    features, masks, assets = inputs()

    for mode in FusionMode:
        output = ThreeAssetMSPCIFormer(fusion_mode=mode)(features, masks, assets)
        assert output.expected_return.shape == (6, 5)


def test_sequence_baseline_outputs_same_forecast_contract() -> None:
    features, masks, assets = inputs()

    output = LSTMForecastBaseline()(features, masks, assets)

    assert output.expected_return.shape == (6, 5)
    assert output.quantiles.shape == (6, 5, 3)


def test_market_only_fallback_triggers_only_for_missing_non_market_sources() -> None:
    _, masks, _ = inputs()
    masks[1, -1, 1, :] = False  # sentiment missing at the decision row
    masks[2, -1, 2, :] = False  # on-chain missing at the decision row
    masks[3, -1, 0, :] = False  # market missing does not trigger the source fallback
    masks[4, :-1, 1, :] = False  # sentiment missing earlier in the window only

    assert requires_market_only_fallback(masks).tolist() == [False, True, True, False, False, False]
