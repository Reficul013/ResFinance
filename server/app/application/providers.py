from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from server.app.domain.crypto import CryptoAsset


@dataclass(frozen=True)
class ProviderObservation:
    asset: CryptoAsset
    metric: str
    observed_at_utc: datetime
    available_at_utc: datetime
    retrieved_at_utc: datetime
    decimal_value: str | None
    missing: bool
    source_reference: str
    provider_revision: str
    response_sha256: str
    terms_reference: str


class MarketDataProvider(Protocol):
    def observations(
        self, *, asset: CryptoAsset, start_utc: datetime, end_utc: datetime
    ) -> Sequence[ProviderObservation]: ...

class OnChainDataProvider(Protocol):
    def observations(
        self, *, asset: CryptoAsset, start_utc: datetime, end_utc: datetime
    ) -> Sequence[ProviderObservation]: ...


class SentimentDataProvider(Protocol):
    def observations(
        self, *, asset: CryptoAsset, start_utc: datetime, end_utc: datetime
    ) -> Sequence[ProviderObservation]: ...
