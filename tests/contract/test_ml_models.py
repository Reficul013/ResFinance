from __future__ import annotations

import hashlib

import torch

from ml.data.datasets import requires_market_only_fallback
from ml.models.mspciformer import FusionMode, LSTMForecastBaseline, ThreeAssetMSPCIFormer
from ml.runs.checkpoints import deterministic_checkpoint, ensemble_checkpoint, restore_models


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


def test_models_support_a_configurable_horizon_count() -> None:
    features, masks, assets = inputs()

    for model in (
        ThreeAssetMSPCIFormer(horizon_count=3),
        LSTMForecastBaseline(horizon_count=3),
    ):
        output = model(features, masks, assets)
        assert output.expected_return.shape == (6, 3)
        assert output.quantiles.shape == (6, 3, 3)


def test_seed_ensemble_checkpoint_round_trips_every_member() -> None:
    features, masks, assets = inputs()
    members = []
    for seed in (11, 23, 37):
        torch.manual_seed(seed)
        members.append(ThreeAssetMSPCIFormer(horizon_count=3))
    content = ensemble_checkpoint(members, model_config={"horizons": [15, 20, 30]})

    restored, digest = restore_models(lambda: ThreeAssetMSPCIFormer(horizon_count=3), content)
    single, _ = restore_models(
        lambda: ThreeAssetMSPCIFormer(horizon_count=3),
        deterministic_checkpoint(members[0], model_config={}),
    )

    assert digest == hashlib.sha256(content).hexdigest()
    assert ensemble_checkpoint(members, model_config={"horizons": [15, 20, 30]}) == content
    assert len(restored) == 3
    assert len(single) == 1
    for original, copy in zip(members, restored, strict=True):
        assert torch.equal(
            original(features, masks, assets).quantiles, copy(features, masks, assets).quantiles
        )
