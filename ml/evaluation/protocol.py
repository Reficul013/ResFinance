from __future__ import annotations

import math
from dataclasses import dataclass
from typing import cast

import torch
from torch import Tensor


@dataclass(frozen=True)
class WalkForwardFold:
    number: int
    train_indices: tuple[int, ...]
    validation_indices: tuple[int, ...]
    test_indices: tuple[int, ...]
    train_end: str
    validation_start: str
    validation_end: str
    test_start: str
    test_end: str
    embargo_days: int


def expanding_walk_forward(
    dates: tuple[str, ...],
    *,
    fold_count: int = 5,
    minimum_train_dates: int = 24,
    validation_dates: int = 6,
    test_dates: int = 5,
    embargo_dates: int = 15,
) -> tuple[WalkForwardFold, ...]:
    if fold_count != 5:
        raise ValueError("Milestone 6 requires exactly five walk-forward folds")
    unique_dates = tuple(dict.fromkeys(dates))
    required = minimum_train_dates + validation_dates + test_dates + 2 * embargo_dates
    required += (fold_count - 1) * test_dates
    if len(unique_dates) < required:
        raise ValueError(f"walk-forward evaluation requires at least {required} decision dates")
    date_to_indices: dict[str, list[int]] = {}
    for index, current in enumerate(dates):
        date_to_indices.setdefault(current, []).append(index)
    folds: list[WalkForwardFold] = []
    for number in range(fold_count):
        train_end_index = minimum_train_dates + number * test_dates
        validation_start_index = train_end_index + embargo_dates
        validation_end_index = validation_start_index + validation_dates
        test_start_index = validation_end_index + embargo_dates
        test_end_index = test_start_index + test_dates
        train_dates = unique_dates[:train_end_index]
        validation_window = unique_dates[validation_start_index:validation_end_index]
        test_window = unique_dates[test_start_index:test_end_index]
        folds.append(
            WalkForwardFold(
                number=number,
                train_indices=_indices(date_to_indices, train_dates),
                validation_indices=_indices(date_to_indices, validation_window),
                test_indices=_indices(date_to_indices, test_window),
                train_end=train_dates[-1],
                validation_start=validation_window[0],
                validation_end=validation_window[-1],
                test_start=test_window[0],
                test_end=test_window[-1],
                embargo_days=embargo_dates,
            )
        )
    return tuple(folds)


def conformalize(
    validation_targets: Tensor,
    validation_lower: Tensor,
    validation_upper: Tensor,
    test_lower: Tensor,
    test_upper: Tensor,
    *,
    alpha: float = 0.2,
) -> tuple[Tensor, Tensor, Tensor]:
    if not 0 < alpha < 1:
        raise ValueError("conformal alpha must be between zero and one")
    scores = torch.maximum(
        validation_lower - validation_targets,
        validation_targets - validation_upper,
    )
    scores = scores.clamp_min(0.0)
    sorted_scores, _ = scores.sort(dim=0)
    rank = min(
        sorted_scores.shape[0] - 1,
        max(0, math.ceil((sorted_scores.shape[0] + 1) * (1.0 - alpha)) - 1),
    )
    adjustment = sorted_scores[rank]
    return test_lower - adjustment, test_upper + adjustment, adjustment


def metric_bundle(
    targets: Tensor,
    expected: Tensor,
    probability_up: Tensor,
    lower: Tensor,
    upper: Tensor,
) -> dict[str, object]:
    if not (targets.shape == expected.shape == probability_up.shape == lower.shape == upper.shape):
        raise ValueError("metric tensors must have identical shapes")
    errors = expected - targets
    actual_up = (targets >= 0).to(targets.dtype)
    direction = ((expected >= 0) == (targets >= 0)).to(targets.dtype)
    coverage = ((targets >= lower) & (targets <= upper)).to(targets.dtype)
    strategy_returns = torch.sign(expected) * targets
    costs: dict[str, float] = {}
    for basis_points in (0, 10, 25):
        turnover_cost = (basis_points / 10_000.0) * (expected != 0).to(expected.dtype)
        costs[str(basis_points)] = _round((strategy_returns - turnover_cost).mean())
    flattened_strategy = strategy_returns.flatten()
    standard_deviation = flattened_strategy.std(unbiased=False)
    sharpe = 0.0
    if float(standard_deviation) > 0:
        sharpe = float(flattened_strategy.mean() / standard_deviation * math.sqrt(252.0))
    wealth = torch.cumprod((1.0 + flattened_strategy).clamp_min(0.01), dim=0)
    running_peak = torch.cummax(wealth, dim=0).values
    maximum_drawdown = float(((wealth - running_peak) / running_peak).min())
    return {
        "sample_count": targets.shape[0],
        "mae": _round(errors.abs().mean()),
        "rmse": _round(torch.sqrt((errors**2).mean())),
        "directional_accuracy": _round(direction.mean()),
        "brier_score": _round(((probability_up - actual_up) ** 2).mean()),
        "interval_coverage": _round(coverage.mean()),
        "interval_mean_width": _round((upper - lower).mean()),
        "annualized_sharpe": _round(sharpe),
        "maximum_drawdown": _round(maximum_drawdown),
        "transaction_cost_mean_return": costs,
    }


def fold_to_dict(fold: WalkForwardFold) -> dict[str, object]:
    return {
        "number": fold.number,
        "train_sample_count": len(fold.train_indices),
        "validation_sample_count": len(fold.validation_indices),
        "test_sample_count": len(fold.test_indices),
        "train_end": fold.train_end,
        "validation_start": fold.validation_start,
        "validation_end": fold.validation_end,
        "test_start": fold.test_start,
        "test_end": fold.test_end,
        "embargo_days": fold.embargo_days,
        "random_shuffling": False,
    }


def _indices(mapping: dict[str, list[int]], selected_dates: tuple[str, ...]) -> tuple[int, ...]:
    return tuple(index for current in selected_dates for index in mapping[current])


def _round(value: Tensor | float) -> float:
    return round(float(cast(float, value)), 10)
