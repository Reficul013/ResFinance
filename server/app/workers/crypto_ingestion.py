from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from server.app.application.crypto_ingestion import (
    CryptoIngestionService,
    IngestionReceipt,
)
from server.app.application.providers import CryptoDataProvider
from server.app.domain.crypto import CryptoAsset


@dataclass(frozen=True)
class IngestionJob:
    job_id: str
    assets: tuple[CryptoAsset, ...]
    start_utc: datetime
    end_utc: datetime


def run_ingestion_job(
    service: CryptoIngestionService,
    job: IngestionJob,
    providers: Sequence[CryptoDataProvider],
) -> tuple[IngestionReceipt, ...]:
    receipts: list[IngestionReceipt] = []
    for provider in providers:
        selected_assets = tuple(asset for asset in job.assets if asset in provider.supported_assets)
        if not selected_assets:
            continue
        receipts.append(
            service.ingest(
                provider,
                assets=selected_assets,
                start_utc=job.start_utc,
                end_utc=job.end_utc,
                attempt_id=f"{job.job_id}-{provider.adapter_id}",
            )
        )
    return tuple(receipts)
