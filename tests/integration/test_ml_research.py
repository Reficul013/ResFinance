from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime

import pytest
import torch

from ml.data.datasets import MaskedStandardizer, build_inference_batch, build_sequence_dataset
from ml.data.synthetic import generate_synthetic_feature_dataset
from ml.evaluation.protocol import expanding_walk_forward
from ml.features.point_in_time import FeatureDataset
from ml.models.mspciformer import FusionMode, ThreeAssetMSPCIFormer
from ml.runs.checkpoints import deterministic_checkpoint, restore_checkpoint
from ml.runs.forward import (
    ForwardResearchResult,
    ForwardRunConfig,
    infer_current_forecast,
    run_forward_research,
    standardizer_from_artifact,
)
from ml.runs.runner import MODEL_ORDER, SmokeRunConfig, run_smoke_research
from server.app.infrastructure.blob_repository import EncryptedBlobRepository
from server.app.infrastructure.encryption import AesGcmCipher, canonical_json_bytes
from server.app.infrastructure.research_repository import PromotionCriteria, ResearchRunRepository


class MemoryKeyValueStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def put(self, key: str, value: str) -> None:
        self.values[key] = value

    def range_values(self, prefix: str) -> Sequence[str]:
        return [self.values[key] for key in sorted(self.values) if key.startswith(prefix)]


@pytest.fixture(scope="module")
def repeated_results() -> tuple[object, object]:
    dataset = generate_synthetic_feature_dataset()
    config = SmokeRunConfig(epochs=2)
    fixed_times = iter(
        (
            datetime(2026, 10, 14, 1, 0, tzinfo=UTC),
            datetime(2026, 10, 14, 1, 1, tzinfo=UTC),
        )
    )
    first = run_smoke_research(
        dataset,
        config=config,
        run_id="repeat-a",
        clock=lambda: next(fixed_times),
    )
    second_times = iter(
        (
            datetime(2026, 10, 14, 2, 0, tzinfo=UTC),
            datetime(2026, 10, 14, 2, 1, tzinfo=UTC),
        )
    )
    second = run_smoke_research(
        dataset,
        config=config,
        run_id="repeat-b",
        clock=lambda: next(second_times),
    )
    return first, second


def test_synthetic_dataset_is_deterministic_and_preserves_missingness() -> None:
    first = generate_synthetic_feature_dataset()
    second = generate_synthetic_feature_dataset()

    assert first.dataset_hash == second.dataset_hash
    assert first.rows == second.rows
    assert first.manifest["assets"] == ["BTC", "ETH", "SOL"]
    sol_missing = [
        row
        for row in first.rows
        if row["asset"] == "SOL" and not row["source_masks"]["on_chain"]  # type: ignore[index]
    ]
    assert sol_missing
    assert all(
        row["values"]["on_chain_solana_tvl_usd"] is None  # type: ignore[index]
        for row in sol_missing
    )


def test_walk_forward_folds_are_chronological_embargoed_and_unshuffled() -> None:
    sequences = build_sequence_dataset(generate_synthetic_feature_dataset())
    folds = expanding_walk_forward(sequences.decision_dates)

    assert len(folds) == 5
    for fold in folds:
        train_dates = {sequences.decision_dates[index] for index in fold.train_indices}
        validation_dates = {sequences.decision_dates[index] for index in fold.validation_indices}
        test_dates = {sequences.decision_dates[index] for index in fold.test_indices}
        assert max(train_dates) < min(validation_dates) < max(validation_dates) < min(test_dates)
        assert train_dates.isdisjoint(validation_dates | test_dates)
        assert fold.embargo_days == 15


def test_adaptive_gating_masks_unavailable_sources() -> None:
    sequences = build_sequence_dataset(generate_synthetic_feature_dataset())
    standardizer = MaskedStandardizer.fit(sequences.features, sequences.masks)
    normalized = standardizer.transform(sequences.features, sequences.masks)
    model = ThreeAssetMSPCIFormer(fusion_mode=FusionMode.ADAPTIVE)
    model.eval()

    with torch.inference_mode():
        output = model(normalized[:12], sequences.masks[:12], sequences.asset_indices[:12])

    source_available = sequences.masks[:12].any(dim=-1)
    assert torch.all(output.gate_weights[~source_available] == 0)
    sums = output.gate_weights.sum(dim=2)
    available_sums = sums[source_available.any(dim=2)]
    assert torch.allclose(available_sums, torch.ones_like(available_sums))


def test_checkpoint_serialization_is_deterministic_and_restorable() -> None:
    torch.manual_seed(22)
    model = ThreeAssetMSPCIFormer()
    first = deterministic_checkpoint(model, model_config={"name": "adaptive-gating"})
    second = deterministic_checkpoint(model, model_config={"name": "adaptive-gating"})
    restored = ThreeAssetMSPCIFormer()

    restored_hash = restore_checkpoint(restored, first)

    assert first == second
    assert restored_hash == hashlib.sha256(first).hexdigest()
    assert all(
        torch.equal(model.state_dict()[name], restored.state_dict()[name])
        for name in model.state_dict()
    )


def test_repeated_cpu_smoke_runs_have_identical_prediction_hashes(
    repeated_results: tuple[object, object],
) -> None:
    first, second = repeated_results
    assert first.dataset_hash == second.dataset_hash  # type: ignore[attr-defined]
    assert first.prediction_hash == second.prediction_hash  # type: ignore[attr-defined]
    manifest = first.manifest  # type: ignore[attr-defined]
    assert manifest["reported_models"] == list(MODEL_ORDER)
    assert manifest["required_comparisons_complete"] is True
    assert len(manifest["folds"]) == 5
    assert manifest["statistical_significance_claim"] is None


def test_run_artifacts_are_encrypted_restorable_and_immutable(
    repeated_results: tuple[object, object],
) -> None:
    result = repeated_results[0]
    store = MemoryKeyValueStore()
    repository = ResearchRunRepository(
        store,
        EncryptedBlobRepository(store, AesGcmCipher(b"m" * 32, key_id="m6-test-v1")),
    )

    first = repository.put_completed_run(result.manifest, result.artifacts)  # type: ignore[attr-defined]
    repeated = repository.put_completed_run(result.manifest, result.artifacts)  # type: ignore[attr-defined]
    restored = repository.restore_artifact(first.run_id, "predictions.json")

    assert not first.deduplicated
    assert repeated.deduplicated
    assert restored == result.artifacts["predictions.json"]  # type: ignore[attr-defined]
    prediction_prefix = restored[:120].decode()
    assert prediction_prefix not in "".join(store.values.values())


def test_promotion_requires_declared_criteria_and_writes_immutable_event(
    repeated_results: tuple[object, object],
) -> None:
    result = repeated_results[0]
    manifest = dict(result.manifest)  # type: ignore[attr-defined]
    metrics = json.loads(json.dumps(manifest["metrics"]))
    metrics["adaptive-gating"]["mae"] = metrics["naive-zero-return"]["mae"] * 0.9
    metrics["adaptive-gating"]["interval_coverage"] = 0.85
    artifacts = dict(result.artifacts)  # type: ignore[attr-defined]
    artifacts["metrics.json"] = canonical_json_bytes(metrics)
    artifact_hashes = dict(manifest["artifact_hashes"])
    artifact_hashes["metrics.json"] = hashlib.sha256(artifacts["metrics.json"]).hexdigest()
    manifest["metrics"] = metrics
    manifest["artifact_hashes"] = artifact_hashes
    store = MemoryKeyValueStore()
    repository = ResearchRunRepository(
        store,
        EncryptedBlobRepository(store, AesGcmCipher(b"p" * 32, key_id="promotion-test-v1")),
    )
    repository.put_completed_run(manifest, artifacts)
    promoted_at = datetime(2026, 10, 14, 3, 0, tzinfo=UTC)

    first = repository.promote_model(
        run_id=str(manifest["run_id"]),
        model_name="adaptive-gating",
        criteria=PromotionCriteria(),
        promoted_at_utc=promoted_at,
        approved_by="milestone6-acceptance",
    )
    repeated = repository.promote_model(
        run_id=str(manifest["run_id"]),
        model_name="adaptive-gating",
        criteria=PromotionCriteria(),
        promoted_at_utc=promoted_at,
        approved_by="milestone6-acceptance",
    )

    assert not first.deduplicated
    assert repeated.deduplicated
    assert first.key.startswith("promotion:forecast:")


def test_fourth_asset_and_incomplete_ablation_report_are_rejected(
    repeated_results: tuple[object, object],
) -> None:
    dataset = generate_synthetic_feature_dataset()
    invalid_dataset = type(dataset)(
        dataset.dataset_hash,
        dataset.rows,
        {**dataset.manifest, "assets": ["BTC", "ETH", "SOL", "DOGE"]},
    )
    with pytest.raises(ValueError, match="exactly BTC, ETH, and SOL"):
        build_sequence_dataset(invalid_dataset)

    result = repeated_results[0]
    manifest = {**result.manifest, "reported_models": list(MODEL_ORDER[:-1])}  # type: ignore[attr-defined]
    repository = ResearchRunRepository(
        MemoryKeyValueStore(),
        EncryptedBlobRepository(
            MemoryKeyValueStore(), AesGcmCipher(b"r" * 32, key_id="reject-test-v1")
        ),
    )
    with pytest.raises(ValueError, match="baseline or ablation"):
        repository.put_completed_run(manifest, result.artifacts)  # type: ignore[attr-defined]


@pytest.fixture(scope="module")
def forward_run() -> tuple[FeatureDataset, ForwardResearchResult]:
    dataset = generate_synthetic_feature_dataset(day_count=700)
    result = run_forward_research(
        dataset,
        config=ForwardRunConfig(epochs=1),
        run_id="forward-protocol-test",
    )
    return dataset, result


def _deployment_models(
    result: ForwardResearchResult,
) -> tuple[ThreeAssetMSPCIFormer, ThreeAssetMSPCIFormer, MaskedStandardizer, dict[str, object]]:
    manifest = result.manifest
    primary = ThreeAssetMSPCIFormer(fusion_mode=FusionMode.ADAPTIVE)
    restore_checkpoint(primary, result.artifacts[str(manifest["deployment_model_artifact"])])
    fallback = ThreeAssetMSPCIFormer(fusion_mode=FusionMode.MARKET_ONLY)
    restore_checkpoint(fallback, result.artifacts[str(manifest["fallback_model_artifact"])])
    standardizer = standardizer_from_artifact(
        result.artifacts[str(manifest["standardizer_artifact"])]
    )
    calibration = manifest["adaptive_calibration"]
    assert isinstance(calibration, dict)
    return primary, fallback, standardizer, calibration


def _with_latest_sentiment_removed(dataset: FeatureDataset, asset: str) -> FeatureDataset:
    latest = max(str(row["timestamp_utc"]) for row in dataset.rows)
    rows = []
    for row in dataset.rows:
        if row["asset"] == asset and row["timestamp_utc"] == latest:
            values = {**row["values"]}  # type: ignore[dict-item]
            masks = {**row["availability_masks"]}  # type: ignore[dict-item]
            for name in values:
                if name.startswith("sentiment_"):
                    values[name] = None
                    masks[name] = False
            row = {**row, "values": values, "availability_masks": masks}
        rows.append(row)
    return FeatureDataset(dataset.dataset_hash, tuple(rows), dataset.manifest)


def test_forward_protocol_uses_frozen_windows_and_immutable_promotion(
    forward_run: tuple[FeatureDataset, ForwardResearchResult],
) -> None:
    _, result = forward_run
    manifest = result.manifest
    holdout = manifest["forward_holdout"]
    calibration = manifest["adaptive_calibration"]
    metrics = manifest["metrics"]

    assert isinstance(holdout, dict)
    assert holdout["training_end"] == "2024-12-17"
    assert holdout["validation_start"] == "2025-01-02"
    assert holdout["holdout_start"] == "2025-04-02"
    assert holdout["post_holdout_tuning_permitted"] is False
    assert isinstance(calibration, dict)
    assert calibration["schema_version"] == 2
    assert calibration["policy"] == "no-change-centre-native-heads-v1"
    assert manifest["fallback_model_artifact"] == "deployment-checkpoint-market-only.json"
    assert isinstance(metrics, dict)
    # The no-change centre makes the candidate's point error identical to zero-return.
    assert metrics["adaptive-gating"]["mae"] == metrics["naive-zero-return"]["mae"]
    assert metrics["adaptive-gating"]["interval_coverage"] >= 0.70

    store = MemoryKeyValueStore()
    repository = ResearchRunRepository(
        store,
        EncryptedBlobRepository(store, AesGcmCipher(b"f" * 32, key_id="forward-test-v1")),
    )
    tampered_manifest = {
        **manifest,
        "adaptive_calibration": {**calibration, "conformal_adjustment": [0.0] * 5},
    }
    with pytest.raises(ValueError, match="calibration artifact"):
        repository.put_completed_run(tampered_manifest, result.artifacts)
    without_fallback = {
        key: value for key, value in manifest.items() if key != "fallback_model_artifact"
    }
    with pytest.raises(ValueError, match="fallback model artifact"):
        repository.put_completed_run(without_fallback, result.artifacts)
    repository.put_completed_run(manifest, result.artifacts)
    promotion = repository.promote_model(
        run_id=result.run_id,
        model_name="adaptive-gating",
        criteria=PromotionCriteria(),
        promoted_at_utc=datetime(2026, 10, 15, tzinfo=UTC),
        approved_by="forward-protocol-test",
    )
    event = repository.promotion_event(promotion.key.removeprefix("promotion:forecast:"))
    assert event["checks"]["untouched_forward_holdout"] is True
    assert event["fallback_model_artifact"] == "deployment-checkpoint-market-only.json"
    assert (
        event["deployment_model_hash"]
        == manifest["artifact_hashes"]["deployment-checkpoint-adaptive-gating.json"]
    )


def test_current_forecast_has_no_change_centre_and_native_ranges(
    forward_run: tuple[FeatureDataset, ForwardResearchResult],
) -> None:
    dataset, result = forward_run
    primary, fallback, standardizer, calibration = _deployment_models(result)

    current = infer_current_forecast(
        dataset,
        model=primary,
        standardizer=standardizer,
        calibration=calibration,
        fallback_model=fallback,
    )

    assert current.fallback_used == (False, False, False)
    assert torch.all(current.expected == 0)
    assert torch.all((current.probability_up > 0) & (current.probability_up < 1))
    assert not torch.all(current.probability_up == 0.5)
    assert torch.all(current.p10 <= current.p50)
    assert torch.all(current.p50 <= current.p90)
    assert torch.all(current.p90 - current.p10 > 0)


def test_stale_sources_switch_that_asset_to_the_market_only_model(
    forward_run: tuple[FeatureDataset, ForwardResearchResult],
) -> None:
    dataset, result = forward_run
    primary, fallback, standardizer, calibration = _deployment_models(result)
    stale = _with_latest_sentiment_removed(dataset, "ETH")

    switched = infer_current_forecast(
        stale,
        model=primary,
        standardizer=standardizer,
        calibration=calibration,
        fallback_model=fallback,
    )
    batch = build_inference_batch(stale)
    with torch.inference_mode():
        normalized = standardizer.transform(batch.features, batch.masks)
        fallback_output = fallback(normalized, batch.masks, batch.asset_indices)
        primary_output = primary(normalized, batch.masks, batch.asset_indices)

    assert switched.fallback_used == (False, True, False)
    assert torch.equal(
        switched.probability_up[1], torch.sigmoid(fallback_output.direction_logits[1])
    )
    assert torch.equal(
        switched.probability_up[0], torch.sigmoid(primary_output.direction_logits[0])
    )
    assert torch.all(switched.expected == 0)
    with pytest.raises(ValueError, match="fallback model"):
        infer_current_forecast(
            stale, model=primary, standardizer=standardizer, calibration=calibration
        )


def test_schema_v1_calibration_keeps_its_shrinkage_behaviour(
    forward_run: tuple[FeatureDataset, ForwardResearchResult],
) -> None:
    dataset, result = forward_run
    primary, _, standardizer, calibration = _deployment_models(result)
    legacy = {
        "schema_version": 1,
        "selected_coefficient": 0.0,
        "conformal_adjustment": calibration["conformal_adjustment"],
    }

    current = infer_current_forecast(
        dataset, model=primary, standardizer=standardizer, calibration=legacy
    )

    assert torch.all(current.expected == 0)
    assert torch.all(current.probability_up == 0.5)
    assert current.fallback_used == (False, False, False)
