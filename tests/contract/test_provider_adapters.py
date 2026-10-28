from __future__ import annotations

import hashlib
import urllib.parse
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from server.app.domain.crypto import CryptoAsset
from server.app.infrastructure.provider_adapters import (
    CoinGeckoCurrentQuoteAdapter,
    CoinMetricsMarketAdapter,
    DefiLlamaSolanaAdapter,
    GdeltDocTimelineAdapter,
    GdeltGkgCsvAdapter,
    JsonResponse,
    fetch_gdelt_doc_json,
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


def _doc_timeline(first: datetime, totals: list[int], *, tone: bool = False) -> dict[str, object]:
    return {
        "timeline": [
            {
                "series": "Average Tone" if tone else "Article Count",
                "data": [
                    {
                        "date": (first + timedelta(days=offset)).strftime("%Y%m%dT%H%M%SZ"),
                        "value": f"-0.{offset + 1}" if tone else str(10 + offset),
                        **({} if tone else {"norm": str(total)}),
                    }
                    for offset, total in enumerate(totals)
                ],
            }
        ]
    }


def test_gdelt_doc_adapter_emits_daily_volume_and_tone_with_two_day_availability() -> None:
    first = datetime(2026, 9, 1, tzinfo=UTC)
    totals = [150_000] * 42
    totals[35] = 4_000  # an outage day: under half the same weekday's recent median
    calls: list[dict[str, list[str]]] = []

    def fetch(url: str) -> JsonResponse:
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        calls.append(query)
        payload = _doc_timeline(first, totals, tone=query["mode"] == ["timelinetone"])
        return JsonResponse(url, datetime(2026, 10, 12, 6, tzinfo=UTC), payload, "a" * 64)

    items = GdeltDocTimelineAdapter(fetcher=fetch).observations(
        assets=(CryptoAsset.SOL,),
        start_utc=datetime(2026, 10, 5, tzinfo=UTC),
        end_utc=datetime(2026, 10, 12, tzinfo=UTC),
    )

    assert [call["mode"] for call in calls] == [["timelinevolraw"], ["timelinetone"]]
    assert calls[0]["startdatetime"] == ["20260907000000"]
    assert "crypto OR cryptocurrency" in calls[0]["query"][0]
    days = sorted({item.observed_at_utc.date().isoformat() for item in items})
    # 10-06 is the outage day; 10-11 and 10-12 are not available two days after they end.
    assert days == ["2026-10-05", "2026-10-07", "2026-10-08", "2026-10-09", "2026-10-10"]
    assert {item.metric for item in items} == {"document_count", "average_tone"}
    assert {item.provider for item in items} == {"gdelt-doc"}
    assert all(item.available_at_utc - item.observed_at_utc == timedelta(days=2) for item in items)
    volume = [item for item in items if item.metric == "document_count"]
    assert volume[0].decimal_value == "44"


def test_gdelt_doc_adapter_rejects_sub_daily_points() -> None:
    def fetch(url: str) -> JsonResponse:
        payload = {"timeline": [{"data": [{"date": "20261010T001500Z", "value": "3"}]}]}
        return JsonResponse(url, datetime(2026, 10, 14, tzinfo=UTC), payload, "b" * 64)

    with pytest.raises(ValueError, match="daily resolution"):
        GdeltDocTimelineAdapter(fetcher=fetch).observations(
            assets=(CryptoAsset.BTC,),
            start_utc=datetime(2026, 10, 10, tzinfo=UTC),
            end_utc=datetime(2026, 10, 10, tzinfo=UTC),
        )


def test_gdelt_doc_fetch_backs_off_after_rate_limit_replies() -> None:
    pauses: list[float] = []
    attempts: list[str] = []

    def fetch(url: str) -> JsonResponse:
        attempts.append(url)
        if len(attempts) < 3:
            raise ValueError("Please limit requests to one every 5 seconds")
        return response(url, {"timeline": []})

    result = fetch_gdelt_doc_json("https://example.test/doc", fetch=fetch, sleep=pauses.append)

    assert result.payload == {"timeline": []}
    assert pauses == [6.0, 15.0, 6.0, 30.0, 6.0]
