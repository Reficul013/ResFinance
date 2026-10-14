from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from server.app.domain.crypto import CryptoAsset
from server.app.infrastructure.provider_adapters import (
    CoinGeckoCurrentQuoteAdapter,
    CoinMetricsMarketAdapter,
    DefiLlamaSolanaAdapter,
    GdeltGkgCsvAdapter,
    JsonResponse,
)


def response(url: str, payload: object, marker: str = "a") -> JsonResponse:
    return JsonResponse(
        url=url,
        retrieved_at_utc=datetime(2026, 10, 14, tzinfo=UTC),
        payload=payload,
        sha256=hashlib.sha256(marker.encode()).hexdigest(),
    )


def test_coin_metrics_adapter_follows_pagination_and_preserves_decimal_strings() -> None:
    calls: list[str] = []

    def fetch(url: str) -> JsonResponse:
        calls.append(url)
        if len(calls) == 1:
            return response(
                url,
                {
                    "data": [
                        {
                            "asset": "btc",
                            "time": "2025-01-01T00:00:00.000000000Z",
                            "PriceUSD": "93452.1200",
                        }
                    ],
                    "next_page_url": "https://example.test/page-2",
                },
            )
        return response(
            url,
            {
                "data": [
                    {
                        "asset": "eth",
                        "time": "2025-01-01T00:00:00.000000000Z",
                        "PriceUSD": "3350.50",
                    }
                ]
            },
            "b",
        )

    items = CoinMetricsMarketAdapter(fetcher=fetch).observations(
        assets=(CryptoAsset.BTC, CryptoAsset.ETH),
        start_utc=datetime(2025, 1, 1, tzinfo=UTC),
        end_utc=datetime(2025, 1, 1, tzinfo=UTC),
    )

    assert len(calls) == 2
    assert [item.asset for item in items] == [CryptoAsset.BTC, CryptoAsset.ETH]
    assert [item.decimal_value for item in items] == ["93452.12", "3350.5"]


def test_defillama_adapter_emits_explicit_missing_masks_instead_of_zero() -> None:
    def fetch(url: str) -> JsonResponse:
        if "historicalChainTvl" in url:
            return response(url, [{"date": "1609459200", "tvl": "123.5"}])
        return response(url, [], "stablecoins")

    items = DefiLlamaSolanaAdapter(fetcher=fetch).observations(
        assets=(CryptoAsset.SOL,),
        start_utc=datetime(2021, 1, 1, tzinfo=UTC),
        end_utc=datetime(2021, 1, 2, tzinfo=UTC),
    )

    assert len(items) == 4
    tvl = [item for item in items if item.metric == "solana_tvl_usd"]
    stablecoins = [item for item in items if item.metric == "solana_stablecoin_supply_usd"]
    assert tvl[0].decimal_value == "123.5" and not tvl[0].missing
    assert tvl[1].decimal_value is None and tvl[1].missing
    assert all(item.decimal_value is None and item.missing for item in stablecoins)


def test_defillama_rejects_non_solana_assets() -> None:
    with pytest.raises(ValueError, match="only SOL"):
        DefiLlamaSolanaAdapter(fetcher=lambda url: response(url, [])).observations(
            assets=(CryptoAsset.BTC,),
            start_utc=datetime(2021, 1, 1, tzinfo=UTC),
            end_utc=datetime(2021, 1, 1, tzinfo=UTC),
        )


def test_coingecko_current_quote_maps_exact_asset_ids_and_provider_time() -> None:
    def fetch(url: str) -> JsonResponse:
        return response(
            url,
            {
                "bitcoin": {"usd": "90000.25", "last_updated_at": "1760000000"},
                "ethereum": {"usd": "3000", "last_updated_at": "1760000000"},
                "solana": {"usd": "150.5", "last_updated_at": "1760000000"},
            },
        )

    items = CoinGeckoCurrentQuoteAdapter(fetcher=fetch).observations(
        assets=tuple(CryptoAsset),
        start_utc=datetime(2025, 1, 1, tzinfo=UTC),
        end_utc=datetime(2025, 1, 1, tzinfo=UTC),
    )

    assert [item.asset for item in items] == list(CryptoAsset)
    assert [item.decimal_value for item in items] == ["90000.25", "3000", "150.5"]
    assert all(item.metric == "price_usd_spot" for item in items)


def test_gdelt_adapter_rejects_fourth_asset_and_preserves_empty_tone_mask(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "gdelt.csv"
    csv_path.write_text(
        "day,asset,document_count,source_count,tone_observation_count,"
        "positive_document_count,negative_document_count,neutral_document_count,"
        "average_tone\n"
        "2025-01-01,BTC,0,0,0,0,0,0,\n",
        encoding="utf-8",
    )
    adapter = GdeltGkgCsvAdapter(
        csv_path,
        source_reference="https://example.test/bounded-query",
        retrieved_at_utc=datetime(2026, 10, 14, tzinfo=UTC),
    )

    items = adapter.observations(
        assets=(CryptoAsset.BTC,),
        start_utc=datetime(2025, 1, 1, tzinfo=UTC),
        end_utc=datetime(2025, 1, 1, tzinfo=UTC),
    )

    document_count = next(item for item in items if item.metric == "document_count")
    average_tone = next(item for item in items if item.metric == "average_tone")
    assert document_count.decimal_value == "0" and not document_count.missing
    assert average_tone.decimal_value is None and average_tone.missing

    csv_path.write_text(
        csv_path.read_text(encoding="utf-8") + "2025-01-01,DOGE,1,1,1,1,0,0,1.0\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="BTC, ETH, or SOL"):
        adapter.observations(
            assets=(CryptoAsset.BTC,),
            start_utc=datetime(2025, 1, 1, tzinfo=UTC),
            end_utc=datetime(2025, 1, 1, tzinfo=UTC),
        )


def test_gdelt_adapter_rejects_an_incomplete_requested_grid(tmp_path: Path) -> None:
    csv_path = tmp_path / "gdelt-incomplete.csv"
    csv_path.write_text(
        "day,asset,document_count,source_count,tone_observation_count,"
        "positive_document_count,negative_document_count,neutral_document_count,"
        "average_tone\n"
        "2025-01-01,BTC,1,1,1,1,0,0,0.25\n",
        encoding="utf-8",
    )
    adapter = GdeltGkgCsvAdapter(
        csv_path,
        source_reference="https://example.test/bounded-query",
        retrieved_at_utc=datetime(2026, 10, 14, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="missing 1 requested"):
        adapter.observations(
            assets=(CryptoAsset.BTC,),
            start_utc=datetime(2025, 1, 1, tzinfo=UTC),
            end_utc=datetime(2025, 1, 2, tzinfo=UTC),
        )
