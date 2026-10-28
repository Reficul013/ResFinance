"""Prospective ledger entries, outcome scoring and the prospective promotion gate.

Protocol v3 (docs/research-protocol.md) scores only forecasts recorded before their outcomes
exist. Each decision date gets one immutable entry holding the deployable forecast and the
no-change baseline; outcomes come from Coin Metrics closes once both prices are stored.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from typing import cast

from torch import Tensor

from server.app.infrastructure.encryption import canonical_json_bytes

PROSPECTIVE_GATE = "forecast-promotion-prospective-v1"
LEDGER_ASSETS = ("BTC", "ETH", "SOL")
LEDGER_MODELS = ("deployable", "no-change")


@dataclass(frozen=True)
class GateCriteria:
    version: str = PROSPECTIVE_GATE
    sample_decision_dates: int = 90
    minimum_coverage: float = 0.70
    maximum_coverage: float = 0.90
    alpha: float = 0.2


def ledger_entry(
    *,
    run_id: str,
    protocol: str,
    decision_time_utc: str,
    issued_at_utc: datetime,
    horizons: Sequence[int],
    expected: Tensor,
    probability_up: Tensor,
    p10: Tensor,
    p50: Tensor,
    p90: Tensor,
    fallback_used: Sequence[bool],
    no_change_adjustment: Sequence[float],
    model_hashes: Mapping[str, str],
    calibration_hash: str,
    dataset_hash: str,
) -> dict[str, object]:
    """One decision date's deployable and no-change forecasts, hashed for the ledger."""
    decision_time = parse_utc(decision_time_utc)
    if len(no_change_adjustment) != len(horizons) or len(fallback_used) != len(LEDGER_ASSETS):
        raise ValueError("ledger forecasts must cover every asset and horizon")
    forecasts: list[dict[str, object]] = []
    for asset_index, asset in enumerate(LEDGER_ASSETS):
        for horizon_index, horizon in enumerate(horizons):
            forecasts.append(
                {
                    "model": "deployable",
                    "asset": asset,
                    "horizon_days": horizon,
                    "path": "fallback" if fallback_used[asset_index] else "primary",
                    "expected_return": _round(expected[asset_index, horizon_index]),
                    "probability_up": _round(probability_up[asset_index, horizon_index]),
                    "p10": _round(p10[asset_index, horizon_index]),
                    "p50": _round(p50[asset_index, horizon_index]),
                    "p90": _round(p90[asset_index, horizon_index]),
                }
            )
            half_width = _round(no_change_adjustment[horizon_index])
            forecasts.append(
                {
                    "model": "no-change",
                    "asset": asset,
                    "horizon_days": horizon,
                    "path": "baseline",
                    "expected_return": 0.0,
                    "probability_up": 0.5,
                    "p10": -half_width,
                    "p50": 0.0,
                    "p90": half_width,
                }
            )
    core: dict[str, object] = {
        "schema_version": 1,
        "protocol": protocol,
        "run_id": run_id,
        "decision_date": (decision_time - timedelta(days=1)).date().isoformat(),
        "decision_time_utc": timestamp(decision_time),
        "issued_at_utc": timestamp(issued_at_utc),
        "horizons": list(horizons),
        "model_hashes": dict(sorted(model_hashes.items())),
        "calibration_hash": calibration_hash,
        "dataset_hash": dataset_hash,
        "forecasts": forecasts,
    }
    return {**core, "entry_hash": entry_hash(core)}


def entry_hash(entry: Mapping[str, object]) -> str:
    core = {key: value for key, value in entry.items() if key != "entry_hash"}
    return hashlib.sha256(canonical_json_bytes(core)).hexdigest()


def score_ledger(
    entries: Sequence[Mapping[str, object]],
    prices: Mapping[tuple[str, date], float],
    *,
    criteria: GateCriteria | None = None,
) -> dict[str, object]:
    """Score matured forecasts and evaluate the gate on the earliest decision dates.

    The gate sample for each horizon is the earliest ``sample_decision_dates`` ledger entries,
    so the decision is a fixed function of the ledger and later looks cannot change it.
    """
    criteria = criteria or GateCriteria()
    ordered = sorted(entries, key=lambda item: str(item["decision_date"]))
    if len({str(item["decision_date"]) for item in ordered}) != len(ordered):
        raise ValueError("prospective ledger repeats a decision date")
    horizons = _horizons(ordered)
    outcomes: dict[tuple[str, str, int], float] = {}
    for entry in ordered:
        if entry.get("entry_hash") != entry_hash(entry):
            raise ValueError("prospective ledger entry hash does not match its content")
        decision_date = date.fromisoformat(str(entry["decision_date"]))
        for asset in LEDGER_ASSETS:
            start = prices.get((asset, decision_date))
            for horizon in horizons:
                end = prices.get((asset, decision_date + timedelta(days=horizon)))
                if start is not None and end is not None:
                    outcomes[(str(entry["decision_date"]), asset, horizon)] = end / start - 1.0

    by_horizon: dict[str, object] = {}
    gate_rows: dict[str, list[tuple[dict[str, object], float]]] = {
        model: [] for model in LEDGER_MODELS
    }
    gate_entry_hashes: set[str] = set()
    sample_complete = len(ordered) >= criteria.sample_decision_dates
    coverage_checks: dict[str, bool] = {}
    for horizon in horizons:
        scored = [
            entry
            for entry in ordered
            if all(
                (str(entry["decision_date"]), asset, horizon) in outcomes for asset in LEDGER_ASSETS
            )
        ]
        scored_dates = {str(entry["decision_date"]) for entry in scored}
        sample = ordered[: criteria.sample_decision_dates]
        sample_scored = sample_complete and all(
            str(entry["decision_date"]) in scored_dates for entry in sample
        )
        summary: dict[str, object] = {
            "scored_decision_dates": len(scored),
            "all_scored": {
                model: _metrics(_rows(scored, outcomes, model, horizon), criteria.alpha)
                for model in LEDGER_MODELS
            },
            "gate_sample": None,
        }
        if sample_scored:
            sample_metrics: dict[str, object] = {}
            for model in LEDGER_MODELS:
                rows = _rows(sample, outcomes, model, horizon)
                gate_rows[model].extend(rows)
                sample_metrics[model] = _metrics(rows, criteria.alpha)
            gate_entry_hashes.update(str(entry["entry_hash"]) for entry in sample)
            coverage = cast(dict[str, float], sample_metrics["deployable"])["coverage"]
            coverage_checks[f"coverage_{horizon}d"] = (
                criteria.minimum_coverage <= coverage <= criteria.maximum_coverage
            )
            summary["gate_sample"] = {
                "first_decision_date": str(sample[0]["decision_date"]),
                "last_decision_date": str(sample[-1]["decision_date"]),
                **sample_metrics,
            }
        by_horizon[str(horizon)] = summary

    cells = {
        f"{asset}-{horizon}d": {
            model: _metrics(
                [
                    row
                    for row in _rows(ordered, outcomes, model, horizon)
                    if row[0]["asset"] == asset
                ],
                criteria.alpha,
            )
            for model in LEDGER_MODELS
        }
        for asset in LEDGER_ASSETS
        for horizon in horizons
    }
    gate: dict[str, object] = {"status": "insufficient-data", "checks": {}, "pooled": None}
    if horizons and len(coverage_checks) == len(horizons):
        pooled = {model: _metrics(gate_rows[model], criteria.alpha) for model in LEDGER_MODELS}
        candidate, baseline = pooled["deployable"], pooled["no-change"]
        checks = {
            **coverage_checks,
            "winkler_not_worse": candidate["winkler"] <= baseline["winkler"],
            "pinball_not_worse": candidate["pinball"] <= baseline["pinball"],
            "brier_not_worse": candidate["brier"] <= baseline["brier"],
        }
        gate = {
            "status": "passed" if all(checks.values()) else "failed",
            "checks": checks,
            "pooled": pooled,
            "entry_hashes": sorted(gate_entry_hashes),
        }
    paths = [
        raw["path"]
        for entry in ordered
        for raw in cast(list[dict[str, object]], entry["forecasts"])
        if raw["model"] == "deployable"
    ]
    return {
        "schema_version": 1,
        "criteria": asdict(criteria),
        "ledger_entry_count": len(ordered),
        "fallback_share": _round(paths.count("fallback") / len(paths)) if paths else None,
        "horizons": by_horizon,
        "cells": cells,
        "gate": gate,
    }


def gate_decision(run_id: str, scorecard: Mapping[str, object]) -> dict[str, object]:
    """The immutable pass/fail record for a run, hashed without its timestamp."""
    gate = cast(dict[str, object], scorecard["gate"])
    if gate.get("status") not in ("passed", "failed"):
        raise ValueError("the prospective gate has not reached a decision")
    core: dict[str, object] = {
        "schema_version": 1,
        "event_type": "research.prospective-gate-decided",
        "run_id": run_id,
        "criteria": scorecard["criteria"],
        "status": gate["status"],
        "checks": gate["checks"],
        "pooled": gate["pooled"],
        "per_horizon_gate_samples": {
            horizon: cast(dict[str, object], summary)["gate_sample"]
            for horizon, summary in cast(dict[str, object], scorecard["horizons"]).items()
        },
        "entry_hashes": gate["entry_hashes"],
    }
    return {**core, "decision_hash": hashlib.sha256(canonical_json_bytes(core)).hexdigest()}


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("ledger timestamps must include a timezone")
    return parsed.astimezone(UTC)


def timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _horizons(entries: Sequence[Mapping[str, object]]) -> tuple[int, ...]:
    values = {tuple(cast(list[int], entry["horizons"])) for entry in entries}
    if len(values) > 1:
        raise ValueError("prospective ledger entries disagree on horizons")
    return values.pop() if values else ()


def _rows(
    entries: Sequence[Mapping[str, object]],
    outcomes: Mapping[tuple[str, str, int], float],
    model: str,
    horizon: int,
) -> list[tuple[dict[str, object], float]]:
    rows: list[tuple[dict[str, object], float]] = []
    for entry in entries:
        for raw in cast(list[dict[str, object]], entry["forecasts"]):
            if raw["model"] != model or raw["horizon_days"] != horizon:
                continue
            outcome = outcomes.get((str(entry["decision_date"]), str(raw["asset"]), horizon))
            if outcome is not None:
                rows.append((raw, outcome))
    return rows


def _metrics(rows: Sequence[tuple[dict[str, object], float]], alpha: float) -> dict[str, float]:
    if not rows:
        return {"count": 0}
    lower_tail = upper_tail = width = winkler = pinball = brier = 0.0
    for forecast, outcome in rows:
        p10, p50, p90 = (float(cast(float, forecast[name])) for name in ("p10", "p50", "p90"))
        probability = float(cast(float, forecast["probability_up"]))
        below, above = outcome < p10, outcome > p90
        lower_tail += below
        upper_tail += above
        width += p90 - p10
        winkler += (p90 - p10) + (2 / alpha) * (max(p10 - outcome, 0.0) + max(outcome - p90, 0.0))
        pinball += (
            sum(
                max(tau * (outcome - quantile), (tau - 1) * (outcome - quantile))
                for tau, quantile in ((0.1, p10), (0.5, p50), (0.9, p90))
            )
            / 3
        )
        brier += (probability - float(outcome > 0)) ** 2
    count = len(rows)
    return {
        "count": count,
        "coverage": _round(1 - (lower_tail + upper_tail) / count),
        "lower_tail_rate": _round(lower_tail / count),
        "upper_tail_rate": _round(upper_tail / count),
        "mean_width": _round(width / count),
        "winkler": _round(winkler / count),
        "pinball": _round(pinball / count),
        "brier": _round(brier / count),
    }


def _round(value: Tensor | float) -> float:
    return round(float(value), 10)
