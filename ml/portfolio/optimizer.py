# mypy: disable-error-code="import-untyped,attr-defined,no-untyped-call,no-any-return"

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal

import cvxpy as cp
import numpy as np
from sklearn.covariance import LedoitWolf

from server.app.domain.crypto import CryptoAsset
from server.app.domain.portfolio import Allocation, AssetForecast, PricePoint

_ASSETS: tuple[CryptoAsset, ...] = tuple(CryptoAsset)


@dataclass(frozen=True)
class OptimizationResult:
    allocations: tuple[Allocation, ...]
    solver: str
    fallback_used: bool
    covariance_repaired: bool


def optimize_portfolio(
    *,
    capital_minor_units: int,
    risk_score: int,
    forecasts: tuple[AssetForecast, ...],
    price_history: tuple[PricePoint, ...],
) -> OptimizationResult:
    if capital_minor_units < 0:
        raise ValueError("portfolio capital cannot be negative")
    if not 0 <= risk_score <= 100:
        raise ValueError("risk score must be between zero and 100")
    forecast_by_asset = {item.asset: item for item in forecasts}
    if set(forecast_by_asset) != set(_ASSETS):
        raise ValueError("forecasts must cover BTC, ETH, and SOL")
    returns = _aligned_daily_returns(price_history)
    covariance = LedoitWolf().fit(returns).covariance_
    covariance *= 15
    covariance, repaired = _nearest_psd(covariance)
    expected = np.array(
        [
            float(Decimal(forecast_by_asset[asset].expected_return))
            - 0.25
            * float(
                Decimal(forecast_by_asset[asset].p90_return)
                - Decimal(forecast_by_asset[asset].p10_return)
            )
            for asset in _ASSETS
        ],
        dtype=np.float64,
    )
    caps = np.array([0.80, 0.60, 0.10 + 0.25 * (risk_score / 100)], dtype=np.float64)
    risk_aversion = 8.0 - 7.0 * (risk_score / 100)
    weights = cp.Variable(len(_ASSETS))
    objective = cp.Maximize(expected @ weights - risk_aversion * cp.quad_form(weights, covariance))
    problem = cp.Problem(objective, [weights >= 0, weights <= caps, cp.sum(weights) == 1])
    solved_with = "CLARABEL"
    fallback = False
    try:
        problem.solve(solver="CLARABEL")
        if problem.status not in {cp.OPTIMAL, cp.OPTIMAL_INACCURATE} or weights.value is None:
            raise cp.SolverError(f"CLARABEL status {problem.status}")
    except cp.SolverError:
        solved_with = "SCS"
        try:
            problem.solve(solver="SCS")
            if problem.status not in {cp.OPTIMAL, cp.OPTIMAL_INACCURATE} or weights.value is None:
                raise cp.SolverError(f"SCS status {problem.status}")
        except cp.SolverError as fallback_error:
            fallback = True
            solved_with = "minimum-variance"
            fallback_problem = cp.Problem(
                cp.Minimize(cp.quad_form(weights, covariance)),
                [weights >= 0, weights <= caps, cp.sum(weights) == 1],
            )
            fallback_problem.solve(solver="CLARABEL")
            if weights.value is None:
                raise ValueError("portfolio optimization failed") from fallback_error
    normalized = _normalize_weights(np.asarray(weights.value, dtype=np.float64), caps)
    amounts = _reconcile_cents(capital_minor_units, normalized)
    allocations = tuple(
        Allocation(
            asset=asset,
            weight=_decimal(normalized[index]),
            amount_minor_units=amounts[index],
            cap=_decimal(caps[index]),
        )
        for index, asset in enumerate(_ASSETS)
    )
    return OptimizationResult(allocations, solved_with, fallback, repaired)


def _aligned_daily_returns(history: tuple[PricePoint, ...]) -> np.ndarray:
    prices: dict[CryptoAsset, dict[str, Decimal]] = {asset: {} for asset in _ASSETS}
    for point in history:
        day = point.observed_at_utc.date().isoformat()
        prices[point.asset][day] = Decimal(point.price_usd)
    common_days = sorted(set.intersection(*(set(values) for values in prices.values())))
    if len(common_days) < 3:
        raise ValueError("at least three aligned price days are required")
    rows: list[list[float]] = []
    for previous_day, current_day in zip(common_days, common_days[1:], strict=False):
        rows.append(
            [
                float(prices[asset][current_day] / prices[asset][previous_day] - Decimal(1))
                for asset in _ASSETS
            ]
        )
    return np.asarray(rows, dtype=np.float64)


def _nearest_psd(matrix: np.ndarray) -> tuple[np.ndarray, bool]:
    symmetric = (matrix + matrix.T) / 2
    values, vectors = np.linalg.eigh(symmetric)
    repaired = bool(np.any(values < 1e-10))
    clipped = np.maximum(values, 1e-10)
    return vectors @ np.diag(clipped) @ vectors.T, repaired


def _normalize_weights(values: np.ndarray, caps: np.ndarray) -> np.ndarray:
    result = np.clip(values, 0, caps)
    for _ in range(8):
        gap = 1.0 - float(result.sum())
        if abs(gap) <= 1e-9:
            break
        if gap > 0:
            available = caps - result
            total = float(available[available > 1e-12].sum())
            if total <= 0:
                raise ValueError("portfolio caps are infeasible")
            result += np.where(available > 1e-12, gap * available / total, 0)
        else:
            total = float(result[result > 1e-12].sum())
            result -= np.where(result > 1e-12, (-gap) * result / total, 0)
        result = np.clip(result, 0, caps)
    return result / result.sum()


def _reconcile_cents(capital: int, weights: np.ndarray) -> tuple[int, ...]:
    exact = [Decimal(capital) * Decimal(str(float(weight))) for weight in weights]
    amounts = [int(value.to_integral_value(rounding=ROUND_FLOOR)) for value in exact]
    remainder = capital - sum(amounts)
    order = sorted(range(len(exact)), key=lambda index: exact[index] - amounts[index], reverse=True)
    for index in order[:remainder]:
        amounts[index] += 1
    return tuple(amounts)


def _decimal(value: float) -> str:
    return format(Decimal(str(value)).quantize(Decimal("0.00000001")), "f")
