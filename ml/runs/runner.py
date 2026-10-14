from __future__ import annotations

import hashlib
import json
import os
import platform
import random
import subprocess
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import numpy as np
import torch
from torch import Tensor, nn
from torch.nn import functional as F

from ml.data.datasets import (
    HORIZONS,
    SOURCE_NAMES,
    MaskedStandardizer,
    ResearchSequenceDataset,
    build_sequence_dataset,
)
from ml.evaluation.protocol import conformalize, expanding_walk_forward, fold_to_dict, metric_bundle
from ml.features.point_in_time import FeatureDataset
from ml.models.mspciformer import (
    FusionMode,
    LSTMForecastBaseline,
    ModelOutput,
    ThreeAssetMSPCIFormer,
)
from ml.runs.checkpoints import deterministic_checkpoint
from server.app.infrastructure.encryption import canonical_json_bytes


@dataclass(frozen=True)
class SmokeRunConfig:
    seed: int = 1731
    lookback: int = 16
    epochs: int = 2
    learning_rate: float = 0.01
    fold_count: int = 5
    minimum_train_dates: int = 24
    validation_dates: int = 6
    test_dates: int = 5
    embargo_dates: int = 15
    conformal_alpha: float = 0.2
    purpose: str = "milestone-6-deterministic-cpu-smoke"
    owner: str = "resfinance-local-research"
    parent_run_id: str | None = None

    def to_dict(self) -> dict[str, object]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class ResearchResult:
    run_id: str
    dataset_hash: str
    prediction_hash: str
    manifest: dict[str, object]
    artifacts: dict[str, bytes]


@dataclass(frozen=True)
class _Forecast:
    expected: Tensor
    probability_up: Tensor
    lower: Tensor
    upper: Tensor
    gate_weights: Tensor | None


MODEL_ORDER = (
    "naive-zero-return",
    "linear-ridge",
    "lstm-sequence",
    FusionMode.MARKET_ONLY.value,
    FusionMode.FIXED_EQUAL.value,
    FusionMode.ADAPTIVE.value,
    FusionMode.WITHOUT_MARKET.value,
    FusionMode.WITHOUT_SENTIMENT.value,
    FusionMode.WITHOUT_ON_CHAIN.value,
)
FUSION_MODES = (
    FusionMode.ADAPTIVE,
    FusionMode.FIXED_EQUAL,
    FusionMode.MARKET_ONLY,
    FusionMode.WITHOUT_MARKET,
    FusionMode.WITHOUT_SENTIMENT,
    FusionMode.WITHOUT_ON_CHAIN,
)


def run_smoke_research(
    feature_dataset: FeatureDataset,
    *,
    config: SmokeRunConfig | None = None,
    repository_root: Path | None = None,
    run_id: str | None = None,
    clock: Callable[[], datetime] | None = None,
) -> ResearchResult:
    config = config or SmokeRunConfig()
    root = (repository_root or Path.cwd()).resolve()
    now = clock or (lambda: datetime.now(UTC))
    started = now().astimezone(UTC)
    identifier = run_id or uuid.uuid4().hex
    _configure_determinism(config.seed)
    sequences = build_sequence_dataset(feature_dataset, lookback=config.lookback)
    folds = expanding_walk_forward(
        sequences.decision_dates,
        fold_count=config.fold_count,
        minimum_train_dates=config.minimum_train_dates,
        validation_dates=config.validation_dates,
        test_dates=config.test_dates,
        embargo_dates=config.embargo_dates,
    )
    prediction_rows: list[dict[str, object]] = []
    aggregate: dict[str, list[Tensor]] = {name: [] for name in MODEL_ORDER}
    aggregate_expected: dict[str, list[Tensor]] = {name: [] for name in MODEL_ORDER}
    aggregate_probability: dict[str, list[Tensor]] = {name: [] for name in MODEL_ORDER}
    aggregate_lower: dict[str, list[Tensor]] = {name: [] for name in MODEL_ORDER}
    aggregate_upper: dict[str, list[Tensor]] = {name: [] for name in MODEL_ORDER}
    checkpoints: dict[str, bytes] = {}
    gate_report: dict[str, dict[str, float]] = {}

    for fold in folds:
        train = torch.tensor(fold.train_indices, dtype=torch.long)
        validation = torch.tensor(fold.validation_indices, dtype=torch.long)
        test = torch.tensor(fold.test_indices, dtype=torch.long)
        standardizer = MaskedStandardizer.fit(
            sequences.features[train], sequences.masks[train]
        )
        normalized = standardizer.transform(sequences.features, sequences.masks)
        forecasts: dict[str, _Forecast] = {}
        forecasts["naive-zero-return"] = _naive_forecast(sequences, validation, test, config)
        forecasts["linear-ridge"] = _linear_forecast(
            sequences, normalized, train, validation, test, config
        )

        neural_specs: list[tuple[str, nn.Module]] = [
            (
                "lstm-sequence",
                _initialized_model(LSTMForecastBaseline(), config.seed, fold.number, 0),
            )
        ]
        for model_index, mode in enumerate(FUSION_MODES, start=1):
            neural_specs.append(
                (
                    mode.value,
                    _initialized_model(
                        ThreeAssetMSPCIFormer(fusion_mode=mode),
                        config.seed,
                        fold.number,
                        model_index,
                    ),
                )
            )
        for name, model in neural_specs:
            _train_neural(model, sequences, normalized, train, config)
            forecasts[name] = _neural_forecast(
                model, sequences, normalized, validation, test, config
            )
            checkpoint = deterministic_checkpoint(
                model,
                model_config={
                    "name": name,
                    "fold": fold.number,
                    "lookback": config.lookback,
                    "horizons": list(HORIZONS),
                },
            )
            checkpoints[f"checkpoint-{name}-fold-{fold.number}.json"] = checkpoint

        for name in MODEL_ORDER:
            forecast = forecasts[name]
            actual = sequences.targets[test]
            aggregate[name].append(actual)
            aggregate_expected[name].append(forecast.expected)
            aggregate_probability[name].append(forecast.probability_up)
            aggregate_lower[name].append(forecast.lower)
            aggregate_upper[name].append(forecast.upper)
            _append_prediction_rows(
                prediction_rows,
                name=name,
                fold=fold.number,
                indices=fold.test_indices,
                sequences=sequences,
                forecast=forecast,
            )
            if forecast.gate_weights is not None:
                weights = forecast.gate_weights.mean(dim=(0, 1))
                gate_report[f"fold-{fold.number}:{name}"] = {
                    source: _round(weights[index])
                    for index, source in enumerate(SOURCE_NAMES)
                }

    metrics = {
        name: metric_bundle(
            torch.cat(aggregate[name]),
            torch.cat(aggregate_expected[name]),
            torch.cat(aggregate_probability[name]),
            torch.cat(aggregate_lower[name]),
            torch.cat(aggregate_upper[name]),
        )
        for name in MODEL_ORDER
    }
    prediction_bytes = canonical_json_bytes(prediction_rows)
    prediction_hash = hashlib.sha256(prediction_bytes).hexdigest()
    metrics_bytes = canonical_json_bytes(metrics)
    gates_bytes = canonical_json_bytes(gate_report)
    plot_bytes = _mae_svg(metrics)
    config_document = config.to_dict()
    config_hash = hashlib.sha256(canonical_json_bytes(config_document)).hexdigest()
    model_hashes = {
        name: hashlib.sha256(content).hexdigest() for name, content in checkpoints.items()
    }
    artifacts = {
        "predictions.json": prediction_bytes,
        "metrics.json": metrics_bytes,
        "gate-weights.json": gates_bytes,
        "walk-forward-mae.svg": plot_bytes,
        **checkpoints,
    }
    artifact_hashes = {
        name: hashlib.sha256(content).hexdigest() for name, content in sorted(artifacts.items())
    }
    completed = now().astimezone(UTC)
    provenance = _provenance(root)
    manifest: dict[str, object] = {
        "schema_version": 1,
        "run_id": identifier,
        "purpose": config.purpose,
        "owner": config.owner,
        "status": "completed",
        "started_at_utc": _timestamp(started),
        "completed_at_utc": _timestamp(completed),
        "assets": ["BTC", "ETH", "SOL"],
        "research_label": "three-asset MSPCIFormer adaptation",
        "parent_run_id": config.parent_run_id,
        "dataset_hash": sequences.dataset_hash,
        "dataset_manifest_hash": hashlib.sha256(
            canonical_json_bytes(feature_dataset.manifest)
        ).hexdigest(),
        "input_record_ids": list(sequences.source_record_ids),
        "feature_schema": feature_dataset.manifest.get("feature_schema"),
        "configuration": config_document,
        "configuration_hash": config_hash,
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
        "folds": [fold_to_dict(fold) for fold in folds],
        "preprocessing": "masked z-score fit independently on each fold training window",
        "conformal": {
            "method": "split conformal on validation window",
            "alpha": config.conformal_alpha,
        },
        "model_hashes": model_hashes,
        "prediction_hash": prediction_hash,
        "artifact_hashes": artifact_hashes,
        "metrics": metrics,
        "gate_weights": gate_report,
        "reported_models": list(MODEL_ORDER),
        "required_comparisons_complete": set(MODEL_ORDER) == set(metrics),
        "statistical_significance_claim": None,
        "warnings": [
            (
                "Synthetic smoke results validate mechanics and reproducibility, "
                "not investment performance."
            ),
            (
                "No statistical significance is claimed without a predeclared powered "
                "test and correction."
            ),
            (
                "This implementation is a clean-room three-asset adaptation; "
                "no author repository code was copied."
            ),
        ],
    }
    return ResearchResult(identifier, sequences.dataset_hash, prediction_hash, manifest, artifacts)


def _initialized_model(model: nn.Module, seed: int, fold: int, model_index: int) -> nn.Module:
    torch.manual_seed(seed + fold * 100 + model_index)
    for module in model.modules():
        if hasattr(module, "reset_parameters"):
            cast(Any, module).reset_parameters()
    return model


def _configure_determinism(seed: int) -> None:
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    if hasattr(torch.backends, "cudnn"):
        torch.backends.cudnn.benchmark = False
        torch.backends.cudnn.deterministic = True


def _train_neural(
    model: nn.Module,
    dataset: ResearchSequenceDataset,
    normalized: Tensor,
    train: Tensor,
    config: SmokeRunConfig,
) -> None:
    model.train()
    optimizer = torch.optim.Adam(model.parameters(), lr=config.learning_rate)
    for _ in range(config.epochs):
        optimizer.zero_grad(set_to_none=True)
        output = cast(
            ModelOutput,
            model(normalized[train], dataset.masks[train], dataset.asset_indices[train]),
        )
        targets = dataset.targets[train]
        expected_loss = F.mse_loss(output.expected_return, targets)
        direction_loss = F.binary_cross_entropy_with_logits(
            output.direction_logits, (targets >= 0).to(targets.dtype)
        )
        quantile_loss = _pinball_loss(output.quantiles, targets)
        loss = expected_loss + 0.2 * direction_loss + 0.1 * quantile_loss
        loss.backward()  # type: ignore[no-untyped-call]
        optimizer.step()


def _pinball_loss(quantiles: Tensor, targets: Tensor) -> Tensor:
    levels = torch.tensor((0.1, 0.5, 0.9), dtype=targets.dtype).reshape(1, 1, 3)
    errors = targets.unsqueeze(-1) - quantiles
    return torch.maximum(levels * errors, (levels - 1.0) * errors).mean()


def _neural_forecast(
    model: nn.Module,
    dataset: ResearchSequenceDataset,
    normalized: Tensor,
    validation: Tensor,
    test: Tensor,
    config: SmokeRunConfig,
) -> _Forecast:
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
        test_output = cast(
            ModelOutput,
            model(normalized[test], dataset.masks[test], dataset.asset_indices[test]),
        )
    lower, upper, _ = conformalize(
        dataset.targets[validation],
        validation_output.quantiles[:, :, 0],
        validation_output.quantiles[:, :, 2],
        test_output.quantiles[:, :, 0],
        test_output.quantiles[:, :, 2],
        alpha=config.conformal_alpha,
    )
    return _Forecast(
        expected=test_output.expected_return,
        probability_up=torch.sigmoid(test_output.direction_logits),
        lower=lower,
        upper=upper,
        gate_weights=test_output.gate_weights,
    )


def _naive_forecast(
    dataset: ResearchSequenceDataset,
    validation: Tensor,
    test: Tensor,
    config: SmokeRunConfig,
) -> _Forecast:
    validation_prediction = torch.zeros_like(dataset.targets[validation])
    test_prediction = torch.zeros_like(dataset.targets[test])
    lower, upper, _ = conformalize(
        dataset.targets[validation],
        validation_prediction,
        validation_prediction,
        test_prediction,
        test_prediction,
        alpha=config.conformal_alpha,
    )
    return _Forecast(test_prediction, torch.full_like(test_prediction, 0.5), lower, upper, None)


def _linear_forecast(
    dataset: ResearchSequenceDataset,
    normalized: Tensor,
    train: Tensor,
    validation: Tensor,
    test: Tensor,
    config: SmokeRunConfig,
) -> _Forecast:
    design = _linear_design(normalized, dataset.masks, dataset.asset_indices)
    train_design = design[train]
    identity = torch.eye(train_design.shape[1], dtype=train_design.dtype)
    coefficients = torch.linalg.solve(
        train_design.T @ train_design + identity * 1e-3,
        train_design.T @ dataset.targets[train],
    )
    validation_prediction = design[validation] @ coefficients
    test_prediction = design[test] @ coefficients
    lower, upper, _ = conformalize(
        dataset.targets[validation],
        validation_prediction,
        validation_prediction,
        test_prediction,
        test_prediction,
        alpha=config.conformal_alpha,
    )
    probability = torch.sigmoid(test_prediction * 20.0)
    return _Forecast(test_prediction, probability, lower, upper, None)


def _linear_design(features: Tensor, masks: Tensor, assets: Tensor) -> Tensor:
    flattened = torch.cat((features, masks.to(features.dtype)), dim=-1).flatten(start_dim=1)
    one_hot = F.one_hot(assets, num_classes=3).to(features.dtype)
    intercept = torch.ones((features.shape[0], 1), dtype=features.dtype)
    return torch.cat((flattened, one_hot, intercept), dim=1)


def _append_prediction_rows(
    rows: list[dict[str, object]],
    *,
    name: str,
    fold: int,
    indices: tuple[int, ...],
    sequences: ResearchSequenceDataset,
    forecast: _Forecast,
) -> None:
    for position, sample_index in enumerate(indices):
        for horizon_index, horizon in enumerate(HORIZONS):
            rows.append(
                {
                    "model": name,
                    "fold": fold,
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


def _provenance(root: Path) -> dict[str, object]:
    git_commit = _command(root, ("git", "rev-parse", "HEAD")) or "unavailable"
    dirty = _command(root, ("git", "status", "--porcelain=v1")) or ""
    diff = _command(root, ("git", "diff", "--binary", "HEAD")) or ""
    dirty_hash = hashlib.sha256((dirty + "\n" + diff).encode()).hexdigest()
    code_files = sorted(
        path for path in (root / "ml").rglob("*.py") if path.is_file()
    )
    code_hash = _files_hash(code_files, root)
    dependency_file = root / "requirements-ml.txt"
    dependency_content = dependency_file.read_text()
    dependency_hash = hashlib.sha256(dependency_content.encode()).hexdigest()
    lock = json.loads((root / "config/milestone0-lock.json").read_text())
    container = cast(dict[str, object], lock["local_container"])
    return {
        "git_commit": git_commit,
        "git_dirty_state_hash": dirty_hash,
        "code_hash": code_hash,
        "dependency_lock_hash": dependency_hash,
        "dependency_lock": [
            line for line in dependency_content.splitlines() if line and not line.startswith("#")
        ],
        "container_image_digest": container["image_digest"],
        "environment": {
            "python": platform.python_version(),
            "pytorch": torch.__version__,
            "numpy": np.__version__,
            "operating_system": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor() or "unreported",
            "python_executable_sha256": hashlib.sha256(
                Path(sys.executable).read_bytes()
            ).hexdigest(),
            "device": "cpu",
        },
    }


def _files_hash(paths: list[Path], root: Path) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(str(path.relative_to(root)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _mae_svg(metrics: dict[str, dict[str, object]]) -> bytes:
    width = 900
    height = 360
    margin = 50
    values = [float(cast(float, metrics[name]["mae"])) for name in MODEL_ORDER]
    maximum = max(values) or 1.0
    bar_width = (width - margin * 2) / len(values)
    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<text x="50" y="28" font-family="sans-serif" font-size="18">'
        "Walk-forward mean absolute error</text>",
    ]
    for index, (name, value) in enumerate(zip(MODEL_ORDER, values, strict=True)):
        bar_height = 240 * value / maximum
        x = margin + index * bar_width + 6
        y = 290 - bar_height
        color = "#2457C5" if name == FusionMode.ADAPTIVE.value else "#7A8AA0"
        elements.append(
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_width - 12:.2f}" '
            f'height="{bar_height:.2f}" fill="{color}"/>'
        )
        elements.append(
            f'<text x="{x + (bar_width - 12) / 2:.2f}" y="310" '
            'font-family="sans-serif" font-size="9" text-anchor="end" '
            f'transform="rotate(-38 {x + (bar_width - 12) / 2:.2f} 310)">{name}</text>'
        )
    elements.append("</svg>")
    return "".join(elements).encode()


def _command(root: Path, args: tuple[str, ...]) -> str | None:
    completed = subprocess.run(args, cwd=root, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def _timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _round(value: Tensor | float) -> float:
    return round(float(value), 10)
