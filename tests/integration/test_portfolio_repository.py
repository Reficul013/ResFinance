from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest

from server.app.domain.crypto import CryptoAsset
from server.app.domain.portfolio import AssetForecast, ForecastSnapshot, PricePoint
from server.app.infrastructure.portfolio_repository import PortfolioResearchRepository

NOW = datetime(2026, 10, 14, 12, tzinfo=UTC)


class MemoryKeyValueStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def put(self, key: str, value: str) -> None:
        self.values[key] = value

    def range_values(self, prefix: str) -> Sequence[str]:
        return [self.values[key] for key in sorted(self.values) if key.startswith(prefix)]


class PromotionFixture:
    def __init__(self, *, available: bool = True) -> None:
        self.available = available

    def promotion_event(self, event_id: str) -> dict[str, object]:
        if not self.available:
            raise KeyError(event_id)
        return {
            "event_id": event_id,
            "event_type": "research.model-promoted",
            "run_id": "run-promoted",
            "model_name": "adaptive-gating",
        }

    def run_manifest(self, run_id: str) -> dict[str, object]:
        assert run_id == "run-promoted"
        return {
            "dataset_hash": "2" * 64,
            "artifact_hashes": {"checkpoint.bin": "1" * 64},
        }


def test_forecast_snapshot_requires_promotion_and_is_immutable() -> None:
    store = MemoryKeyValueStore()
    repository = PortfolioResearchRepository(store, PromotionFixture())  # type: ignore[arg-type]
    snapshot = _snapshot()

    first = repository.put_forecast_snapshot(snapshot)
    repeated = repository.put_forecast_snapshot(snapshot)
    restored = repository.latest_forecast_snapshot()

    assert not first.deduplicated
    assert repeated.deduplicated
    assert restored == snapshot


def test_forecast_snapshot_without_promotion_is_rejected() -> None:
    repository = PortfolioResearchRepository(
        MemoryKeyValueStore(),
        PromotionFixture(available=False),  # type: ignore[arg-type]
    )

    with pytest.raises(KeyError):
        repository.put_forecast_snapshot(_snapshot())


def _snapshot() -> ForecastSnapshot:
    forecasts = tuple(
        AssetForecast(
            asset=asset,
            expected_return="0.03",
            probability_up="0.55",
            p10_return="-0.04",
            p50_return="0.03",
            p90_return="0.09",
        )
        for asset in CryptoAsset
    )
    prices = tuple(
        PricePoint(
            asset=asset,
            observed_at_utc=NOW - timedelta(days=offset),
            price_usd=str(100 + offset),
            source_record_id=f"price-{asset.value}-{offset}",
        )
        for offset in range(5)
        for asset in CryptoAsset
    )
    return ForecastSnapshot(
        as_of_utc=NOW,
        expires_at_utc=NOW + timedelta(days=1),
        horizon_days=15,
        run_id="run-promoted",
        model_name="adaptive-gating",
        model_hash="1" * 64,
        dataset_hash="2" * 64,
        promotion_event_id="3" * 64,
        forecasts=forecasts,
        price_history=prices,
    )
