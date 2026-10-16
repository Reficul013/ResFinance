from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast

import torch
from torch import Tensor, nn

from ml.data.datasets import (
    HORIZONS,
    SOURCE_NAMES,
    MaskedStandardizer,
    ResearchSequenceDataset,
    build_inference_batch,
    build_sequence_dataset,
)
from ml.evaluation.protocol import conformalize, metric_bundle
from ml.features.point_in_time import FeatureDataset
from ml.models.mspciformer import (
    FusionMode,
    LSTMForecastBaseline,
    ModelOutput,
    ThreeAssetMSPCIFormer,
)
from ml.runs import runner as base_runner
from ml.runs.checkpoints import deterministic_checkpoint
from ml.runs.runner import MODEL_ORDER, SmokeRunConfig
from server.app.infrastructure.encryption import canonical_json_bytes

CALIBRATION_GRID = (0.0, 0.25, 0.5, 0.75, 1.0)


@dataclass(frozen=True)
class ForwardRunConfig:
    seed: int = 1731
    lookback: int = 16
    epochs: int = 20
    learning_rate: float = 0.01
    conformal_alpha: float = 0.2
    training_end: date = date(2024, 12, 17)
    validation_start: date = date(2025, 1, 2)
    validation_end: date = date(2025, 3, 17)
    holdout_start: date = date(2025, 4, 2)
    purpose: str = "milestone-9-untouched-forward-completion"
    owner: str = "resfinance-local-research"

    def to_dict(self) -> dict[str, object]:
        return {
            "seed": self.seed,
            "lookback": self.lookback,
            "epochs": self.epochs,
            "learning_rate": self.learning_rate,
            "conformal_alpha": self.conformal_alpha,
            "training_end": self.training_end.isoformat(),
            "validation_start": self.validation_start.isoformat(),
            "validation_end": self.validation_end.isoformat(),
            "holdout_start": self.holdout_start.isoformat(),
            "calibration_grid": list(CALIBRATION_GRID),
            "purpose": self.purpose,
            "owner": self.owner,
        }


@dataclass(frozen=True)
class ForwardResearchResult:
    run_id: str
    dataset_hash: str
    prediction_hash: str
    manifest: dict[str, object]
    artifacts: dict[str, bytes]


@dataclass(frozen=True)
class CurrentForecast:
    decision_time_utc: str
    expected: Tensor
    probability_up: Tensor
    p10: Tensor
    p50: Tensor
    p90: Tensor


@dataclass(frozen=True)
class _Forecast:
    expected: Tensor
    probability_up: Tensor
    lower: Tensor
    upper: Tensor
    gate_weights: Tensor | None


def run_forward_research(
    feature_dataset: FeatureDataset,
    *,
    config: ForwardRunConfig | None = None,
    repository_root: Path | None = None,
    run_id: str | None = None,
    clock: Callable[[], datetime] | None = None,
) -> ForwardResearchResult:
    config = config or ForwardRunConfig()
    root = (repository_root or Path.cwd()).resolve()
    now = clock or (lambda: datetime.now(UTC))
    started = now().astimezone(UTC)
    identifier = run_id or f"milestone9-forward-{uuid.uuid4().hex}"
    base_runner._configure_determinism(config.seed)
    sequences = build_sequence_dataset(feature_dataset, lookback=config.lookback)
    train = _indices_through(sequences, config.training_end)
    validation = _indices_between(sequences, config.validation_start, config.validation_end)
    holdout = _indices_from(sequences, config.holdout_start)
    if not train.numel() or not validation.numel() or not holdout.numel():
        raise ValueError("forward protocol windows must all contain samples")
    _verify_disjoint(train, validation, holdout)
    standardizer = MaskedStandardizer.fit(sequences.features[train], sequences.masks[train])
    normalized = standardizer.transform(sequences.features, sequences.masks)
    forecasts: dict[str, _Forecast] = {}
    checkpoints: dict[str, bytes] = {}
    gate_report: dict[str, dict[str, float]] = {}

    forecasts["naive-zero-return"] = _naive(sequences, validation, holdout, config)
    forecasts["linear-ridge"] = _linear(sequences, normalized, train, validation, holdout, config)
    adaptive_calibration: dict[str, object] | None = None
    neural_specs: list[tuple[str, nn.Module]] = [
        (
            "lstm-sequence",
            base_runner._initialized_model(LSTMForecastBaseline(), config.seed, 0, 0),
        )
    ]
    modes = (
        FusionMode.ADAPTIVE,
        FusionMode.FIXED_EQUAL,
        FusionMode.MARKET_ONLY,
        FusionMode.WITHOUT_MARKET,
        FusionMode.WITHOUT_SENTIMENT,
        FusionMode.WITHOUT_ON_CHAIN,
    )
    for model_index, mode in enumerate(modes, start=1):
        neural_specs.append(
            (
                mode.value,
                base_runner._initialized_model(
                    ThreeAssetMSPCIFormer(fusion_mode=mode), config.seed, 0, model_index
                ),
            )
        )
    for name, model in neural_specs:
        base_runner._train_neural(
            model,
            sequences,
            normalized,
            train,
            SmokeRunConfig(
                seed=config.seed,
                lookback=config.lookback,
                epochs=config.epochs,
                learning_rate=config.learning_rate,
                conformal_alpha=config.conformal_alpha,
            ),
        )
        forecast, calibration = _neural(
            model,
            sequences,
            normalized,
            validation,
            holdout,
            config,
            calibrate_reliability=name == FusionMode.ADAPTIVE.value,
        )
        forecasts[name] = forecast
        checkpoint = deterministic_checkpoint(
            model,
            model_config={
                "name": name,
                "protocol": "untouched-forward-holdout-v1",
                "lookback": config.lookback,
                "horizons": list(HORIZONS),
            },
        )
        artifact_name = f"checkpoint-{name}.json"
        checkpoints[artifact_name] = checkpoint
        if name == FusionMode.ADAPTIVE.value:
            checkpoints["deployment-checkpoint-adaptive-gating.json"] = checkpoint
            adaptive_calibration = calibration
        if forecast.gate_weights is not None:
            weights = forecast.gate_weights.mean(dim=(0, 1))
            gate_report[name] = {
                source: _round(weights[index]) for index, source in enumerate(SOURCE_NAMES)
            }
    if adaptive_calibration is None:
        raise AssertionError("adaptive calibration was not produced")

    metrics = {
        name: metric_bundle(
            sequences.targets[holdout],
            forecasts[name].expected,
            forecasts[name].probability_up,
            forecasts[name].lower,
            forecasts[name].upper,
        )
        for name in MODEL_ORDER
    }
    prediction_rows = _prediction_rows(sequences, holdout, forecasts)
    prediction_bytes = canonical_json_bytes(prediction_rows)
    prediction_hash = hashlib.sha256(prediction_bytes).hexdigest()
    calibration_bytes = canonical_json_bytes(adaptive_calibration)
    standardizer_bytes = canonical_json_bytes(
        {
            "schema_version": 1,
            "means": standardizer.means.tolist(),
            "scales": standardizer.scales.tolist(),
        }
    )
    artifacts = {
        "predictions.json": prediction_bytes,
        "metrics.json": canonical_json_bytes(metrics),
        "gate-weights.json": canonical_json_bytes(gate_report),
        "adaptive-calibration.json": calibration_bytes,
        "standardizer.json": standardizer_bytes,
        **checkpoints,
    }
    artifact_hashes = {
        name: hashlib.sha256(content).hexdigest() for name, content in sorted(artifacts.items())
    }
    config_document = config.to_dict()
    provenance = base_runner._provenance(root)
    completed = now().astimezone(UTC)
    manifest: dict[str, object] = {
        "schema_version": 2,
        "run_id": identifier,
        "purpose": config.purpose,
        "owner": config.owner,
        "status": "completed",
        "started_at_utc": _timestamp(started),
        "completed_at_utc": _timestamp(completed),
        "assets": ["BTC", "ETH", "SOL"],
        "research_label": "three-asset MSPCIFormer adaptation",
        "dataset_hash": sequences.dataset_hash,
        "dataset_manifest_hash": hashlib.sha256(
            canonical_json_bytes(feature_dataset.manifest)
        ).hexdigest(),
        "input_record_ids": list(sequences.source_record_ids),
        "feature_schema": feature_dataset.manifest.get("feature_schema"),
        "configuration": config_document,
        "configuration_hash": hashlib.sha256(canonical_json_bytes(config_document)).hexdigest(),
        "git_commit": provenance["git_commit"],
        "git_dirty_state_hash": provenance["git_dirty_state_hash"],
        "code_hash": provenance["code_hash"],
        "dependency_lock_hash": provenance["dependency_lock_hash"],
        "dependency_lock": provenance["dependency_lock"],
        "container_image_digest": provenance["container_image_digest"],
        "environment": provenance["environment"],
        "seeds": {
            "python": config.seed,
            "numpy": config.seed,
            "framework": config.seed,
            "data_loader": config.seed,
            "optimizer": config.seed,
        },
        "determinism": {
            "cpu_only": True,
            "deterministic_algorithms": True,
            "random_shuffling": False,
            "torch_threads": 1,
            "known_nondeterministic_operations": [],
        },
        "evaluation_protocol": "untouched-forward-holdout-v1",
        "forward_holdout": {
            "predeclared_at_utc": "2026-10-15T00:00:00Z",
            "training_end": config.training_end.isoformat(),
            "validation_start": config.validation_start.isoformat(),
            "validation_end": config.validation_end.isoformat(),
            "holdout_start": config.holdout_start.isoformat(),
            "holdout_end": _sample_date(sequences, int(holdout[-1])),
            "train_sample_count": int(train.numel()),
            "validation_sample_count": int(validation.numel()),
            "holdout_sample_count": int(holdout.numel()),
            "embargo_days": 15,
            "holdout_labels_consumed_once": True,
            "post_holdout_tuning_permitted": False,
        },
        "folds": [],
        "preprocessing": "masked z-score fit only through the frozen training cutoff",
        "conformal": {
            "method": "split conformal on the frozen validation window",
            "alpha": config.conformal_alpha,
            "adaptive_adjustment": adaptive_calibration["conformal_adjustment"],
        },
        "adaptive_calibration": adaptive_calibration,
        "evaluated_model_artifact": "checkpoint-adaptive-gating.json",
        "deployment_model_artifact": "deployment-checkpoint-adaptive-gating.json",
        "standardizer_artifact": "standardizer.json",
        "model_hashes": {
            name: hashlib.sha256(content).hexdigest() for name, content in checkpoints.items()
        },
        "prediction_hash": prediction_hash,
        "artifact_hashes": artifact_hashes,
        "metrics": metrics,
        "gate_weights": gate_report,
        "reported_models": list(MODEL_ORDER),
        "required_comparisons_complete": set(MODEL_ORDER) == set(metrics),
        "statistical_significance_claim": None,
        "warnings": base_runner._warnings(config.purpose),
    }
    return ForwardResearchResult(
        identifier,
        sequences.dataset_hash,
        prediction_hash,
        manifest,
        artifacts,
    )


def infer_current_forecast(
    feature_dataset: FeatureDataset,
    *,
    model: ThreeAssetMSPCIFormer,
    standardizer: MaskedStandardizer,
    calibration: dict[str, object],
    lookback: int = 16,
) -> CurrentForecast:
    batch = build_inference_batch(feature_dataset, lookback=lookback)
    normalized = standardizer.transform(batch.features, batch.masks)
    model.eval()
    with torch.inference_mode():
        output = cast(ModelOutput, model(normalized, batch.masks, batch.asset_indices))
    coefficient = float(cast(float, calibration["selected_coefficient"]))
    adjustment = torch.tensor(
        cast(list[float], calibration["conformal_adjustment"]), dtype=output.quantiles.dtype
    )
    expected = output.expected_return * coefficient
    probability = 0.5 + coefficient * (torch.sigmoid(output.direction_logits) - 0.5)
    quantiles = output.quantiles * coefficient
    lower = quantiles[:, :, 0] - adjustment
    median = quantiles[:, :, 1]
    upper = quantiles[:, :, 2] + adjustment
    return CurrentForecast(
        decision_time_utc=batch.decision_time_utc,
        expected=expected,
        probability_up=probability,
        p10=torch.minimum(lower, median),
        p50=median,
        p90=torch.maximum(upper, median),
    )


def standardizer_from_artifact(content: bytes) -> MaskedStandardizer:
    value = json.loads(content)
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("unsupported standardizer artifact")
    return MaskedStandardizer(
        means=torch.tensor(value["means"], dtype=torch.float32),
        scales=torch.tensor(value["scales"], dtype=torch.float32),
    )


def _neural(
    model: nn.Module,
    dataset: ResearchSequenceDataset,
    normalized: Tensor,
    validation: Tensor,
    holdout: Tensor,
    config: ForwardRunConfig,
    *,
    calibrate_reliability: bool,
) -> tuple[_Forecast, dict[str, object]]:
    model.eval()
    with torch.inference_mode():
        validation_output = cast(
            ModelOutput,
            model(
                normalized[validation],
                dataset.masks[validation],
                dataset.asset_indices[validation],
            ),
        )
        holdout_output = cast(
            ModelOutput,
            model(normalized[holdout], dataset.masks[holdout], dataset.asset_indices[holdout]),
        )
    grid = CALIBRATION_GRID if calibrate_reliability else (1.0,)
    scores = {
        f"{coefficient:.2f}": _round(
            (validation_output.expected_return * coefficient - dataset.targets[validation])
            .abs()
            .mean()
        )
        for coefficient in grid
    }
    coefficient = min(grid, key=lambda item: (scores[f"{item:.2f}"], item))
    validation_quantiles = validation_output.quantiles * coefficient
    holdout_quantiles = holdout_output.quantiles * coefficient
    lower, upper, adjustment = conformalize(
        dataset.targets[validation],
        validation_quantiles[:, :, 0],
        validation_quantiles[:, :, 2],
        holdout_quantiles[:, :, 0],
        holdout_quantiles[:, :, 2],
        alpha=config.conformal_alpha,
    )
    forecast = _Forecast(
        expected=holdout_output.expected_return * coefficient,
        probability_up=0.5 + coefficient * (torch.sigmoid(holdout_output.direction_logits) - 0.5),
        lower=lower,
        upper=upper,
        gate_weights=holdout_output.gate_weights,
    )
    calibration = {
        "schema_version": 1,
        "selection_window": {
            "start": config.validation_start.isoformat(),
            "end": config.validation_end.isoformat(),
        },
        "grid": list(grid),
        "validation_mae_by_coefficient": scores,
        "selected_coefficient": coefficient,
        "tie_break": "smallest-coefficient",
        "conformal_alpha": config.conformal_alpha,
        "conformal_adjustment": [_round(value) for value in adjustment],
    }
    return forecast, calibration


def _naive(
    dataset: ResearchSequenceDataset,
    validation: Tensor,
    holdout: Tensor,
    config: ForwardRunConfig,
) -> _Forecast:
    validation_prediction = torch.zeros_like(dataset.targets[validation])
    prediction = torch.zeros_like(dataset.targets[holdout])
    lower, upper, _ = conformalize(
        dataset.targets[validation],
        validation_prediction,
        validation_prediction,
        prediction,
        prediction,
        alpha=config.conformal_alpha,
    )
    return _Forecast(prediction, torch.full_like(prediction, 0.5), lower, upper, None)


def _linear(
    dataset: ResearchSequenceDataset,
    normalized: Tensor,
    train: Tensor,
    validation: Tensor,
    holdout: Tensor,
    config: ForwardRunConfig,
) -> _Forecast:
    design = base_runner._linear_design(normalized, dataset.masks, dataset.asset_indices)
    train_design = design[train]
    identity = torch.eye(train_design.shape[1], dtype=train_design.dtype)
    coefficients = torch.linalg.solve(
        train_design.T @ train_design + identity * 1e-3,
        train_design.T @ dataset.targets[train],
    )
    validation_prediction = design[validation] @ coefficients
    prediction = design[holdout] @ coefficients
    lower, upper, _ = conformalize(
        dataset.targets[validation],
        validation_prediction,
        validation_prediction,
        prediction,
        prediction,
        alpha=config.conformal_alpha,
    )
    return _Forecast(prediction, torch.sigmoid(prediction * 20.0), lower, upper, None)


def _prediction_rows(
    sequences: ResearchSequenceDataset,
    indices: Tensor,
    forecasts: dict[str, _Forecast],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for name in MODEL_ORDER:
        forecast = forecasts[name]
        for position, sample_index in enumerate(indices.tolist()):
            for horizon_index, horizon in enumerate(HORIZONS):
                rows.append(
                    {
                        "model": name,
                        "protocol": "untouched-forward-holdout-v1",
                        "decision_time_utc": sequences.decision_dates[sample_index],
                        "asset": sequences.assets[sample_index],
                        "horizon_days": horizon,
                        "actual_return": _round(sequences.targets[sample_index, horizon_index]),
                        "expected_return": _round(forecast.expected[position, horizon_index]),
                        "probability_up": _round(forecast.probability_up[position, horizon_index]),
                        "p10": _round(forecast.lower[position, horizon_index]),
                        "p90": _round(forecast.upper[position, horizon_index]),
                    }
                )
    return rows


def _indices_through(dataset: ResearchSequenceDataset, end: date) -> Tensor:
    return torch.tensor(
        [index for index, value in enumerate(dataset.decision_dates) if _date(value) <= end],
        dtype=torch.long,
    )


def _indices_between(dataset: ResearchSequenceDataset, start: date, end: date) -> Tensor:
    return torch.tensor(
        [
            index
            for index, value in enumerate(dataset.decision_dates)
            if start <= _date(value) <= end
        ],
        dtype=torch.long,
    )


def _indices_from(dataset: ResearchSequenceDataset, start: date) -> Tensor:
    return torch.tensor(
        [index for index, value in enumerate(dataset.decision_dates) if _date(value) >= start],
        dtype=torch.long,
    )


def _verify_disjoint(*indices: Tensor) -> None:
    sets = [set(value.tolist()) for value in indices]
    if any(left & right for offset, left in enumerate(sets) for right in sets[offset + 1 :]):
        raise ValueError("forward protocol windows overlap")


def _sample_date(dataset: ResearchSequenceDataset, index: int) -> str:
    return _date(dataset.decision_dates[index]).isoformat()


def _date(value: str) -> date:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()


def _timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _round(value: Tensor | float) -> float:
    return round(float(value), 10)
