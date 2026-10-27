from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import cast

import torch
from torch import Tensor, nn

from ml.data.datasets import (
    SOURCE_NAMES,
    MaskedStandardizer,
    ResearchSequenceDataset,
    build_inference_batch,
    build_sequence_dataset,
    requires_market_only_fallback,
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
from ml.runs.checkpoints import ensemble_checkpoint
from ml.runs.runner import MODEL_ORDER, SmokeRunConfig
from server.app.infrastructure.encryption import canonical_json_bytes

FORECAST_POLICY = "no-change-centre-native-heads-v1"
FALLBACK_MODEL_ARTIFACT = "deployment-checkpoint-market-only.json"
FORWARD_PROTOCOL = "untouched-forward-holdout-v2"
# The exploratory 15-30 day study scored the period from 2025-04-01 once on 2026-10-26.
EXPLORATORY_HOLDOUT_SCORED = date(2026, 10, 26)


@dataclass(frozen=True)
class ForwardRunConfig:
    """Forward protocol v2, predeclared 2026-10-27 in docs/research-protocol.md."""

    seed: int = 1731
    seeds: tuple[int, ...] = (11, 23, 37)
    horizons: tuple[int, ...] = (15, 20, 30)
    lookback: int = 16
    epochs: int = 100
    learning_rate: float = 0.001
    conformal_alpha: float = 0.2
    training_end: date = date(2024, 1, 30)
    validation_start: date = date(2024, 3, 1)
    validation_end: date = date(2025, 2, 28)
    holdout_start: date = date(2025, 4, 1)
    embargo_days: int = 30
    predeclared_at_utc: str = "2026-10-27T00:00:00Z"
    protocol: str = FORWARD_PROTOCOL
    purpose: str = "forward-protocol-v2-untouched-forward-completion"
    owner: str = "resfinance-local-research"

    def to_dict(self) -> dict[str, object]:
        return {
            "protocol": self.protocol,
            "predeclared_at_utc": self.predeclared_at_utc,
            "seed": self.seed,
            "seeds": list(self.seeds),
            "horizons": list(self.horizons),
            "embargo_days": self.embargo_days,
            "lookback": self.lookback,
            "epochs": self.epochs,
            "learning_rate": self.learning_rate,
            "conformal_alpha": self.conformal_alpha,
            "training_end": self.training_end.isoformat(),
            "validation_start": self.validation_start.isoformat(),
            "validation_end": self.validation_end.isoformat(),
            "holdout_start": self.holdout_start.isoformat(),
            "forecast_policy": FORECAST_POLICY,
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
    fallback_used: tuple[bool, ...] = ()


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
    if not config.seeds or len(set(config.seeds)) != len(config.seeds):
        raise ValueError("forward protocol seeds must be a non-empty unique sequence")
    sequences = build_sequence_dataset(
        feature_dataset, lookback=config.lookback, horizons=config.horizons
    )
    train = _indices_through(sequences, config.training_end)
    validation = _indices_between(sequences, config.validation_start, config.validation_end)
    holdout = _indices_from(sequences, config.holdout_start)
    if not train.numel() or not validation.numel() or not holdout.numel():
        raise ValueError("forward protocol windows must all contain samples")
    _verify_disjoint(train, validation, holdout)
    _verify_targets_mature(sequences, (train, validation, holdout), max(config.horizons))
    standardizer = MaskedStandardizer.fit(sequences.features[train], sequences.masks[train])
    normalized = standardizer.transform(sequences.features, sequences.masks)
    forecasts: dict[str, _Forecast] = {}
    checkpoints: dict[str, bytes] = {}
    gate_report: dict[str, dict[str, float]] = {}

    forecasts["naive-zero-return"] = _naive(sequences, validation, holdout, config)
    forecasts["linear-ridge"] = _linear(sequences, normalized, train, validation, holdout, config)
    trained: dict[str, list[nn.Module]] = {}
    horizon_count = len(config.horizons)
    modes = (
        FusionMode.ADAPTIVE,
        FusionMode.FIXED_EQUAL,
        FusionMode.MARKET_ONLY,
        FusionMode.WITHOUT_MARKET,
        FusionMode.WITHOUT_SENTIMENT,
        FusionMode.WITHOUT_ON_CHAIN,
    )
    factories: list[tuple[str, Callable[[], nn.Module]]] = [
        ("lstm-sequence", lambda: LSTMForecastBaseline(horizon_count=horizon_count)),
        *(
            (
                mode.value,
                lambda mode=mode: ThreeAssetMSPCIFormer(
                    fusion_mode=mode, horizon_count=horizon_count
                ),
            )
            for mode in modes
        ),
    ]
    training = SmokeRunConfig(
        seed=config.seed,
        lookback=config.lookback,
        epochs=config.epochs,
        learning_rate=config.learning_rate,
        conformal_alpha=config.conformal_alpha,
    )
    for model_index, (name, factory) in enumerate(factories):
        members: list[nn.Module] = []
        for seed in config.seeds:
            model = base_runner._initialized_model(factory(), seed, 0, model_index)
            base_runner._train_neural(model, sequences, normalized, train, training)
            members.append(model)
        trained[name] = members
        forecasts[name] = _neural(members, sequences, normalized, validation, holdout, config)
        checkpoint = ensemble_checkpoint(
            members,
            model_config={
                "name": name,
                "protocol": config.protocol,
                "lookback": config.lookback,
                "horizons": list(config.horizons),
                "seeds": list(config.seeds),
            },
        )
        checkpoints[f"checkpoint-{name}.json"] = checkpoint
        if name == FusionMode.ADAPTIVE.value:
            checkpoints["deployment-checkpoint-adaptive-gating.json"] = checkpoint
        if name == FusionMode.MARKET_ONLY.value:
            checkpoints[FALLBACK_MODEL_ARTIFACT] = checkpoint
        gate_weights = forecasts[name].gate_weights
        if gate_weights is not None:
            weights = gate_weights.mean(dim=(0, 1))
            gate_report[name] = {
                source: _round(weights[index]) for index, source in enumerate(SOURCE_NAMES)
            }
    forecasts[FusionMode.ADAPTIVE.value], adaptive_calibration = _deployable(
        trained[FusionMode.ADAPTIVE.value],
        trained[FusionMode.MARKET_ONLY.value],
        sequences,
        normalized,
        validation,
        holdout,
        config,
    )

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
    holdout_previously_observed = config.holdout_start <= EXPLORATORY_HOLDOUT_SCORED
    manifest: dict[str, object] = {
        "schema_version": 3,
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
            "ensemble": list(config.seeds),
        },
        "determinism": {
            "cpu_only": True,
            "deterministic_algorithms": True,
            "random_shuffling": False,
            "torch_threads": 1,
            "known_nondeterministic_operations": [],
        },
        "evaluation_protocol": config.protocol,
        "forward_holdout": {
            "predeclared_at_utc": config.predeclared_at_utc,
            "training_end": config.training_end.isoformat(),
            "validation_start": config.validation_start.isoformat(),
            "validation_end": config.validation_end.isoformat(),
            "holdout_start": config.holdout_start.isoformat(),
            "holdout_end": _sample_date(sequences, int(holdout[-1])),
            "train_sample_count": int(train.numel()),
            "validation_sample_count": int(validation.numel()),
            "holdout_sample_count": int(holdout.numel()),
            "embargo_days": config.embargo_days,
            "horizons": list(config.horizons),
            "seeds": list(config.seeds),
            "holdout_labels_consumed_once": True,
            "post_holdout_tuning_permitted": False,
            "holdout_previously_observed": holdout_previously_observed,
            "holdout_note": (
                "scored once by the exploratory 15-30 day study on "
                f"{EXPLORATORY_HOLDOUT_SCORED.isoformat()}; this result confirms the "
                "implementation and is not new untouched evidence"
                if holdout_previously_observed
                else "untouched at predeclaration"
            ),
        },
        "folds": [],
        "preprocessing": "masked z-score fit only through the frozen training cutoff",
        "conformal": {
            "method": "split conformal on the frozen validation window",
            "alpha": config.conformal_alpha,
            "adaptive_adjustment": adaptive_calibration["conformal_adjustment"],
        },
        "forecast_policy": FORECAST_POLICY,
        "adaptive_calibration": adaptive_calibration,
        "evaluated_model_artifact": "checkpoint-adaptive-gating.json",
        "deployment_model_artifact": "deployment-checkpoint-adaptive-gating.json",
        "fallback_model_artifact": FALLBACK_MODEL_ARTIFACT,
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
    model: nn.Module | Sequence[nn.Module],
    standardizer: MaskedStandardizer,
    calibration: dict[str, object],
    lookback: int = 16,
    fallback_model: nn.Module | Sequence[nn.Module] | None = None,
) -> CurrentForecast:
    """Current forecast from a model or seed ensemble; ensembles average their predictions."""
    batch = build_inference_batch(feature_dataset, lookback=lookback)
    normalized = standardizer.transform(batch.features, batch.masks)
    output = _ensemble(_members(model), normalized, batch.masks, batch.asset_indices)
    adjustment = torch.tensor(
        cast(list[float], calibration["conformal_adjustment"]), dtype=output.quantiles.dtype
    )
    if calibration.get("schema_version") == 2:
        if calibration.get("policy") != FORECAST_POLICY:
            raise ValueError("unsupported forecast policy")
        switch = requires_market_only_fallback(batch.masks)
        quantiles, probability = output.quantiles, output.probability
        if bool(switch.any()):
            if fallback_model is None:
                raise ValueError("stale or missing sources require the market-only fallback model")
            fallback = _ensemble(
                _members(fallback_model), normalized, batch.masks, batch.asset_indices
            )
            quantiles = torch.where(switch.reshape(-1, 1, 1), fallback.quantiles, quantiles)
            probability = torch.where(switch.reshape(-1, 1), fallback.probability, probability)
        expected = torch.zeros_like(probability)
        fallback_used = tuple(bool(value) for value in switch.tolist())
    else:
        # Schema-v1 runs used a validation-selected reliability shrinkage coefficient.
        coefficient = float(cast(float, calibration["selected_coefficient"]))
        expected = output.expected * coefficient
        probability = 0.5 + coefficient * (output.probability - 0.5)
        quantiles = output.quantiles * coefficient
        fallback_used = (False,) * len(batch.assets)
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
        fallback_used=fallback_used,
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
    models: Sequence[nn.Module],
    dataset: ResearchSequenceDataset,
    normalized: Tensor,
    validation: Tensor,
    holdout: Tensor,
    config: ForwardRunConfig,
) -> _Forecast:
    """Report an ablation's seed-averaged outputs with split-conformal ranges."""
    validation_output, holdout_output = _outputs(models, dataset, normalized, validation, holdout)
    lower, upper, _ = conformalize(
        dataset.targets[validation],
        validation_output.quantiles[:, :, 0],
        validation_output.quantiles[:, :, 2],
        holdout_output.quantiles[:, :, 0],
        holdout_output.quantiles[:, :, 2],
        alpha=config.conformal_alpha,
    )
    return _Forecast(
        expected=holdout_output.expected,
        probability_up=holdout_output.probability,
        lower=lower,
        upper=upper,
        gate_weights=holdout_output.gate_weights,
    )


def _deployable(
    adaptive: Sequence[nn.Module],
    market_only: Sequence[nn.Module],
    dataset: ResearchSequenceDataset,
    normalized: Tensor,
    validation: Tensor,
    holdout: Tensor,
    config: ForwardRunConfig,
) -> tuple[_Forecast, dict[str, object]]:
    """No-change centre with the native range and direction heads.

    The expected return is fixed at zero because no evaluated point forecast beat the
    zero-return baseline; ranges and P(up) come from the seed-averaged native heads. Samples
    whose sentiment or on-chain source is missing or stale use the market-only model instead.
    """
    primary = _outputs(adaptive, dataset, normalized, validation, holdout)
    fallback = _outputs(market_only, dataset, normalized, validation, holdout)
    switches = (
        requires_market_only_fallback(dataset.masks[validation]),
        requires_market_only_fallback(dataset.masks[holdout]),
    )
    quantiles = [
        torch.where(switch.reshape(-1, 1, 1), fallback[index].quantiles, primary[index].quantiles)
        for index, switch in enumerate(switches)
    ]
    probability = torch.where(
        switches[1].reshape(-1, 1), fallback[1].probability, primary[1].probability
    )
    lower, upper, adjustment = conformalize(
        dataset.targets[validation],
        quantiles[0][:, :, 0],
        quantiles[0][:, :, 2],
        quantiles[1][:, :, 0],
        quantiles[1][:, :, 2],
        alpha=config.conformal_alpha,
    )
    median = quantiles[1][:, :, 1]
    forecast = _Forecast(
        expected=torch.zeros_like(median),
        probability_up=probability,
        lower=torch.minimum(lower, median),
        upper=torch.maximum(upper, median),
        gate_weights=primary[1].gate_weights,
    )
    calibration: dict[str, object] = {
        "schema_version": 2,
        "policy": FORECAST_POLICY,
        "centre": "no-change: the expected return is fixed at zero",
        "range_source": "seed-averaged native quantile head with a split-conformal adjustment",
        "probability_source": "seed-averaged native direction head",
        "horizons": list(config.horizons),
        "seeds": list(config.seeds),
        "stale_source_policy": {
            "rule": (
                "use the market-only fusion model for an asset whose sentiment or on-chain "
                "source is missing or older than the feature builder's maximum source age"
            ),
            "fallback_model_artifact": FALLBACK_MODEL_ARTIFACT,
        },
        "selection_window": {
            "start": config.validation_start.isoformat(),
            "end": config.validation_end.isoformat(),
        },
        "conformal_alpha": config.conformal_alpha,
        "conformal_adjustment": [_round(value) for value in adjustment],
        "validation_fallback_share": _round(switches[0].to(torch.float32).mean()),
        "holdout_fallback_share": _round(switches[1].to(torch.float32).mean()),
    }
    return forecast, calibration


@dataclass(frozen=True)
class _EnsembleOutput:
    expected: Tensor
    probability: Tensor
    quantiles: Tensor
    gate_weights: Tensor


def _members(model: nn.Module | Sequence[nn.Module]) -> list[nn.Module]:
    return [model] if isinstance(model, nn.Module) else list(model)


def _ensemble(
    models: Sequence[nn.Module], features: Tensor, masks: Tensor, assets: Tensor
) -> _EnsembleOutput:
    """Average expected return, P(up) after the sigmoid, quantiles and gates over models."""
    if not models:
        raise ValueError("an ensemble needs at least one model")
    outputs: list[ModelOutput] = []
    with torch.inference_mode():
        for model in models:
            model.eval()
            outputs.append(cast(ModelOutput, model(features, masks, assets)))
    return _EnsembleOutput(
        expected=torch.stack([item.expected_return for item in outputs]).mean(dim=0),
        probability=torch.stack([torch.sigmoid(item.direction_logits) for item in outputs]).mean(
            dim=0
        ),
        quantiles=torch.stack([item.quantiles for item in outputs]).mean(dim=0),
        gate_weights=torch.stack([item.gate_weights for item in outputs]).mean(dim=0),
    )


def _outputs(
    models: Sequence[nn.Module],
    dataset: ResearchSequenceDataset,
    normalized: Tensor,
    validation: Tensor,
    holdout: Tensor,
) -> tuple[_EnsembleOutput, _EnsembleOutput]:
    validation_output, holdout_output = (
        _ensemble(models, normalized[index], dataset.masks[index], dataset.asset_indices[index])
        for index in (validation, holdout)
    )
    return validation_output, holdout_output


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
            for horizon_index, horizon in enumerate(sequences.horizons):
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


def _verify_targets_mature(
    dataset: ResearchSequenceDataset, windows: Sequence[Tensor], horizon: int
) -> None:
    """Every target in a window must mature before the next window's first decision date."""
    for earlier, later in zip(windows, windows[1:], strict=False):
        last = _date(dataset.decision_dates[int(earlier[-1])])
        first = _date(dataset.decision_dates[int(later[0])])
        if last + timedelta(days=horizon) >= first:
            raise ValueError("forward protocol targets overlap the next window")


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
