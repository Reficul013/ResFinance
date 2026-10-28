from __future__ import annotations

import csv
import hashlib
import io
import json
import time as clock
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Protocol, cast

from server.app.domain.crypto import (
    CryptoAsset,
    ObservationChannel,
    ProviderObservation,
)

COIN_METRICS_TERMS = "https://github.com/coinmetrics/data"
COINGECKO_TERMS = "https://www.coingecko.com/en/api_terms"
DEFILLAMA_TERMS = "https://enterprise.defillama.com/terms"
GDELT_TERMS = "https://www.gdeltproject.org/about.html#termsofuse"
GDELT_DOC_QUERIES = {
    CryptoAsset.BTC: "bitcoin",
    CryptoAsset.ETH: "ethereum",
    # "solana" alone also matches Javier Solana and Solana Beach, so SOL needs crypto context.
    CryptoAsset.SOL: "solana (crypto OR cryptocurrency OR blockchain OR token OR defi)",
}


@dataclass(frozen=True)
class JsonResponse:
    url: str
    retrieved_at_utc: datetime
    payload: object
    sha256: str


class JsonFetcher(Protocol):
    def __call__(self, url: str) -> JsonResponse: ...


def fetch_json(url: str) -> JsonResponse:
    request = urllib.request.Request(url, headers={"User-Agent": "ResFinance-Milestone5/1.0"})
    retrieved = datetime.now(UTC)
    with urllib.request.urlopen(request, timeout=60) as response:
        content = response.read()
    return JsonResponse(
        url=url,
        retrieved_at_utc=retrieved,
        payload=json.loads(content, parse_float=str, parse_int=str),
        sha256=hashlib.sha256(content).hexdigest(),
    )


class CoinMetricsAdapter:
    provider = "coin-metrics"

    def __init__(
        self,
        *,
        channel: ObservationChannel,
        metrics: Mapping[str, str],
        fetcher: JsonFetcher = fetch_json,
        provider_revision: str = "community-api-v4",
    ) -> None:
        if channel not in (ObservationChannel.MARKET, ObservationChannel.ON_CHAIN):
            raise ValueError("Coin Metrics supports market or on-chain observations")
        self._channel = channel
        self._metrics = dict(metrics)
        self._fetcher = fetcher
        self._provider_revision = provider_revision
        self.adapter_id = (
            "coin-metrics-market"
            if channel is ObservationChannel.MARKET
            else "coin-metrics-on-chain"
        )
        self.supported_assets: frozenset[CryptoAsset] = (
            frozenset((CryptoAsset.BTC, CryptoAsset.ETH, CryptoAsset.SOL))
            if channel is ObservationChannel.MARKET
            else frozenset((CryptoAsset.BTC, CryptoAsset.ETH))
        )

    def observations(
        self,
        *,
        assets: Sequence[CryptoAsset],
        start_utc: datetime,
        end_utc: datetime,
    ) -> Sequence[ProviderObservation]:
        if self._channel is ObservationChannel.ON_CHAIN and CryptoAsset.SOL in assets:
            raise ValueError("Coin Metrics V1 on-chain metrics support BTC and ETH only")
        query = urllib.parse.urlencode(
            {
                "assets": ",".join(asset.value.lower() for asset in assets),
                "metrics": ",".join(self._metrics),
                "frequency": "1d",
                "start_time": start_utc.date().isoformat(),
                "end_time": end_utc.date().isoformat(),
                "page_size": "10000",
                "paging_from": "start",
            }
        )
        next_url: str | None = (
            "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?" + query
        )
        result: list[ProviderObservation] = []
        while next_url:
            response = self._fetcher(next_url)
            body = _object(response.payload, "Coin Metrics response")
            rows = body.get("data")
            if not isinstance(rows, list):
                raise ValueError("Coin Metrics response data must be a list")
            for raw in rows:
                row = _object(raw, "Coin Metrics row")
                asset = CryptoAsset.parse(str(row["asset"]).upper())
                if asset not in assets:
                    raise ValueError("Coin Metrics returned an unrequested asset")
                observed = _parse_provider_time(str(row["time"]))
                available = observed + timedelta(days=1)
                for provider_metric, metric in self._metrics.items():
                    raw_value = row.get(provider_metric)
                    value = None if raw_value is None else _decimal(str(raw_value))
                    result.append(
                        ProviderObservation(
                            asset=asset,
                            channel=self._channel,
                            metric=metric,
                            interval="1d",
                            observed_at_utc=observed,
                            available_at_utc=available,
                            retrieved_at_utc=response.retrieved_at_utc,
                            decimal_value=value,
                            missing=value is None,
                            provider=self.provider,
                            source_reference=response.url,
                            provider_revision=self._provider_revision,
                            response_sha256=response.sha256,
                            terms_reference=COIN_METRICS_TERMS,
                            license_status=("cc-by-nc-4.0-noncommercial-research-with-attribution"),
                        )
                    )
            raw_next = body.get("next_page_url")
            next_url = str(raw_next) if raw_next else None
        return result


class CoinMetricsMarketAdapter(CoinMetricsAdapter):
    def __init__(self, *, fetcher: JsonFetcher = fetch_json) -> None:
        super().__init__(
            channel=ObservationChannel.MARKET,
            metrics={"PriceUSD": "price_usd"},
            fetcher=fetcher,
        )


class CoinMetricsOnChainAdapter(CoinMetricsAdapter):
    def __init__(self, *, fetcher: JsonFetcher = fetch_json) -> None:
        super().__init__(
            channel=ObservationChannel.ON_CHAIN,
            metrics={
                "AdrActCnt": "active_addresses",
                "TxCnt": "transaction_count",
            },
            fetcher=fetcher,
        )


class CoinGeckoCurrentQuoteAdapter:
    provider = "coingecko"
    adapter_id = "coingecko-current-quote"
    supported_assets: frozenset[CryptoAsset] = frozenset(
        (CryptoAsset.BTC, CryptoAsset.ETH, CryptoAsset.SOL)
    )
    _ids = {
        CryptoAsset.BTC: "bitcoin",
        CryptoAsset.ETH: "ethereum",
        CryptoAsset.SOL: "solana",
    }

    def __init__(self, *, fetcher: JsonFetcher = fetch_json) -> None:
        self._fetcher = fetcher

    def observations(
        self,
        *,
        assets: Sequence[CryptoAsset],
        start_utc: datetime,
        end_utc: datetime,
    ) -> Sequence[ProviderObservation]:
        del start_utc, end_utc
        query = urllib.parse.urlencode(
            {
                "ids": ",".join(self._ids[asset] for asset in assets),
                "vs_currencies": "usd",
                "include_last_updated_at": "true",
            }
        )
        response = self._fetcher(f"https://api.coingecko.com/api/v3/simple/price?{query}")
        body = _object(response.payload, "CoinGecko response")
        observations: list[ProviderObservation] = []
        for asset in assets:
            provider_id = self._ids[asset]
            quote = _object(body.get(provider_id), f"CoinGecko {provider_id} quote")
            observed = datetime.fromtimestamp(int(str(quote.get("last_updated_at"))), UTC)
            value = _decimal(str(quote["usd"]))
            observations.append(
                ProviderObservation(
                    asset=asset,
                    channel=ObservationChannel.MARKET,
                    metric="price_usd_spot",
                    interval="spot",
                    observed_at_utc=observed,
                    available_at_utc=observed,
                    retrieved_at_utc=response.retrieved_at_utc,
                    decimal_value=value,
                    missing=False,
                    provider=self.provider,
                    source_reference=response.url,
                    provider_revision="simple-price-v3",
                    response_sha256=response.sha256,
                    terms_reference=COINGECKO_TERMS,
                    license_status="current-display-with-attribution-no-redistribution",
                )
            )
        return observations


class DefiLlamaSolanaAdapter:
    provider = "defillama"
    adapter_id = "defillama-solana-proxies"
    supported_assets = frozenset((CryptoAsset.SOL,))
    _sources = (
        (
            "https://api.llama.fi/v2/historicalChainTvl/Solana",
            "solana_tvl_usd",
            ("tvl",),
            "historical-chain-tvl-v2",
        ),
        (
            "https://stablecoins.llama.fi/stablecoincharts/Solana",
            "solana_stablecoin_supply_usd",
            ("totalCirculatingUSD", "peggedUSD"),
            "stablecoincharts-v1",
        ),
    )

    def __init__(self, *, fetcher: JsonFetcher = fetch_json) -> None:
        self._fetcher = fetcher

    def observations(
        self,
        *,
        assets: Sequence[CryptoAsset],
        start_utc: datetime,
        end_utc: datetime,
    ) -> Sequence[ProviderObservation]:
        if tuple(assets) != (CryptoAsset.SOL,):
            raise ValueError("DefiLlama V1 adapter accepts only SOL")
        result: list[ProviderObservation] = []
        for url, metric, path, revision in self._sources:
            response = self._fetcher(url)
            if not isinstance(response.payload, list):
                raise ValueError("DefiLlama response must be a list")
            by_date: dict[date, str] = {}
            for raw in response.payload:
                row = _object(raw, "DefiLlama row")
                observed_date = datetime.fromtimestamp(int(str(row["date"])), UTC).date()
                if not start_utc.date() <= observed_date <= end_utc.date():
                    continue
                value: object = row
                for part in path:
                    if not isinstance(value, dict):
                        value = None
                        break
                    value = value.get(part)
                if value is not None:
                    parsed = _decimal(str(value))
                    previous = by_date.get(observed_date)
                    if previous is not None and previous != parsed:
                        raise ValueError("DefiLlama response has conflicting duplicate dates")
                    by_date[observed_date] = parsed
            current = start_utc.date()
            while current <= end_utc.date():
                observed = datetime.combine(current, time.min, tzinfo=UTC)
                value = by_date.get(current)
                result.append(
                    ProviderObservation(
                        asset=CryptoAsset.SOL,
                        channel=ObservationChannel.ON_CHAIN,
                        metric=metric,
                        interval="1d",
                        observed_at_utc=observed,
                        available_at_utc=observed + timedelta(days=1),
                        retrieved_at_utc=response.retrieved_at_utc,
                        decimal_value=value,
                        missing=value is None,
                        provider=self.provider,
                        source_reference=response.url,
                        provider_revision=revision,
                        response_sha256=response.sha256,
                        terms_reference=DEFILLAMA_TERMS,
                        license_status="personal-noncommercial-research-only",
                    )
                )
                current += timedelta(days=1)
        return result


class GdeltGkgCsvAdapter:
    provider = "gdelt"
    adapter_id = "gdelt-gkg-daily-aggregate"
    supported_assets: frozenset[CryptoAsset] = frozenset(
        (CryptoAsset.BTC, CryptoAsset.ETH, CryptoAsset.SOL)
    )
    _count_metrics = (
        "document_count",
        "source_count",
        "tone_observation_count",
        "positive_document_count",
        "negative_document_count",
        "neutral_document_count",
    )

    def __init__(
        self,
        csv_path: Path,
        *,
        source_reference: str,
        retrieved_at_utc: datetime | None = None,
    ) -> None:
        self._csv_path = csv_path
        self._source_reference = source_reference
        self._retrieved_at = retrieved_at_utc or datetime.now(UTC)

    def observations(
        self,
        *,
        assets: Sequence[CryptoAsset],
        start_utc: datetime,
        end_utc: datetime,
    ) -> Sequence[ProviderObservation]:
        content = self._csv_path.read_bytes()
        response_hash = hashlib.sha256(content).hexdigest()
        rows = csv.DictReader(io.StringIO(content.decode("utf-8")))
        required = {"day", "asset", "average_tone", *self._count_metrics}
        if rows.fieldnames is None or not required.issubset(rows.fieldnames):
            raise ValueError("GDELT CSV is missing required aggregate columns")
        requested = set(assets)
        result: list[ProviderObservation] = []
        seen: set[tuple[date, CryptoAsset]] = set()
        for line, row in enumerate(rows, start=2):
            observed_date = date.fromisoformat(row["day"])
            asset = CryptoAsset.parse(row["asset"])
            if asset not in requested:
                raise ValueError("GDELT CSV contains an unrequested asset")
            if not start_utc.date() <= observed_date <= end_utc.date():
                continue
            identity = (observed_date, asset)
            if identity in seen:
                raise ValueError(f"duplicate GDELT day/asset row at line {line}")
            seen.add(identity)
            observed = datetime.combine(observed_date, time.min, tzinfo=UTC)
            counts = {metric: _nonnegative_integer(row[metric]) for metric in self._count_metrics}
            if counts["source_count"] > counts["document_count"]:
                raise ValueError(f"GDELT source count exceeds documents at line {line}")
            if counts["tone_observation_count"] > counts["document_count"]:
                raise ValueError(f"GDELT tone count exceeds documents at line {line}")
            classified = (
                counts["positive_document_count"]
                + counts["negative_document_count"]
                + counts["neutral_document_count"]
            )
            if classified != counts["tone_observation_count"]:
                raise ValueError(f"GDELT tone classes are inconsistent at line {line}")
            average_tone = row["average_tone"].strip()
            if counts["tone_observation_count"] == 0 and average_tone:
                raise ValueError(f"GDELT average tone exists without observations at line {line}")
            if counts["tone_observation_count"] > 0 and not average_tone:
                raise ValueError(f"GDELT average tone is missing at line {line}")
            for metric in (*self._count_metrics, "average_tone"):
                raw_value = str(counts[metric]) if metric in counts else average_tone
                value = _decimal(raw_value) if raw_value else None
                result.append(
                    ProviderObservation(
                        asset=asset,
                        channel=ObservationChannel.SENTIMENT,
                        metric=metric,
                        interval="1d",
                        observed_at_utc=observed,
                        available_at_utc=observed + timedelta(days=2),
                        retrieved_at_utc=self._retrieved_at,
                        decimal_value=value,
                        missing=value is None,
                        provider=self.provider,
                        source_reference=self._source_reference,
                        provider_revision="gkg-2.1-bigquery-v1",
                        response_sha256=response_hash,
                        terms_reference=GDELT_TERMS,
                        license_status="use-and-redistribution-with-attribution",
                    )
                )
        expected = {
            (current, asset)
            for asset in requested
            for current in _dates(start_utc.date(), end_utc.date())
        }
        missing = expected - seen
        if missing:
            raise ValueError(f"GDELT CSV is missing {len(missing)} requested day/asset rows")
        return result


def fetch_gdelt_doc_json(
    url: str,
    *,
    fetch: JsonFetcher = fetch_json,
    sleep: Callable[[float], None] = clock.sleep,
    attempts: int = 8,
) -> JsonResponse:
    """Fetch one DOC API response, pausing first and backing off on rate-limit replies.

    GDELT asks for at most one request every five seconds and answers faster callers with a
    plain-text message instead of JSON, which surfaces here as a decoding error.
    """
    delay = 15.0
    for attempt in range(attempts):
        sleep(6.0)
        try:
            return fetch(url)
        except (OSError, ValueError):
            if attempt == attempts - 1:
                raise
            sleep(delay)
            delay = min(delay * 2, 600.0)
    raise ValueError("GDELT DOC fetch needs at least one attempt")


class GdeltDocTimelineAdapter:
    """Daily matching-article volume and average tone from the GDELT DOC 2.0 timeline API.

    A day is available two days after it ends, so days not yet available at retrieval are
    dropped. GDELT outages leave days with only a fraction of the usual monitored articles and
    are never back-filled; a day whose monitored total is below half the median of the same
    weekday in the four preceding weeks is dropped, so an outage reads as missing news rather
    than a collapse in coverage. Each request therefore starts 28 days early.
    """

    provider = "gdelt-doc"
    adapter_id = "gdelt-doc-timeline"
    provider_revision = "doc-2.0-timeline-v1"
    supported_assets: frozenset[CryptoAsset] = frozenset(GDELT_DOC_QUERIES)
    publication_lag = timedelta(days=2)
    outage_ratio = Decimal("0.5")
    _modes = (("timelinevolraw", "document_count"), ("timelinetone", "average_tone"))

    def __init__(self, *, fetcher: JsonFetcher = fetch_gdelt_doc_json) -> None:
        self._fetcher = fetcher

    def observations(
        self,
        *,
        assets: Sequence[CryptoAsset],
        start_utc: datetime,
        end_utc: datetime,
    ) -> Sequence[ProviderObservation]:
        first, last = start_utc.date(), end_utc.date()
        if last < first:
            raise ValueError("GDELT DOC request end cannot precede start")
        query_start = first - timedelta(days=28)
        result: list[ProviderObservation] = []
        for asset in assets:
            if asset not in GDELT_DOC_QUERIES:
                raise ValueError("GDELT DOC adapter supports BTC, ETH, and SOL only")
            # The volume request runs first and decides which days both metrics may use.
            complete: set[datetime] = set()
            for mode, metric in self._modes:
                query = urllib.parse.urlencode(
                    {
                        "query": GDELT_DOC_QUERIES[asset],
                        "mode": mode,
                        "startdatetime": query_start.strftime("%Y%m%d") + "000000",
                        "enddatetime": last.strftime("%Y%m%d") + "235959",
                        "format": "json",
                    }
                )
                response = self._fetcher(f"https://api.gdeltproject.org/api/v2/doc/doc?{query}")
                points = _gdelt_doc_daily_points(response.payload)
                if mode == "timelinevolraw":
                    complete = self._complete_days(points)
                for observed, (value, _) in sorted(points.items()):
                    available = observed + self.publication_lag
                    if (
                        not first <= observed.date() <= last
                        or available > response.retrieved_at_utc
                        or observed not in complete
                    ):
                        continue
                    result.append(
                        ProviderObservation(
                            asset=asset,
                            channel=ObservationChannel.SENTIMENT,
                            metric=metric,
                            interval="1d",
                            observed_at_utc=observed,
                            available_at_utc=available,
                            retrieved_at_utc=response.retrieved_at_utc,
                            decimal_value=value,
                            missing=False,
                            provider=self.provider,
                            source_reference=response.url,
                            provider_revision=self.provider_revision,
                            response_sha256=response.sha256,
                            terms_reference=GDELT_TERMS,
                            license_status="use-and-redistribution-with-attribution",
                        )
                    )
        return result

    def _complete_days(self, points: Mapping[datetime, tuple[str, str | None]]) -> set[datetime]:
        totals = {day: Decimal(total) for day, (_, total) in points.items() if total is not None}
        complete: set[datetime] = set()
        for day, total in totals.items():
            prior = sorted(
                totals[earlier]
                for weeks in range(1, 5)
                if (earlier := day - timedelta(days=7 * weeks)) in totals
            )
            if len(prior) < 2:
                continue
            middle = len(prior) // 2
            median = prior[middle] if len(prior) % 2 else (prior[middle - 1] + prior[middle]) / 2
            if total >= median * self.outage_ratio:
                complete.add(day)
        return complete


def _gdelt_doc_daily_points(payload: object) -> dict[datetime, tuple[str, str | None]]:
    """Daily values with the monitored-article total (``norm``) when the mode reports it."""
    timeline = _object(payload, "GDELT DOC response").get("timeline")
    if not isinstance(timeline, list):
        raise ValueError("GDELT DOC response timeline must be a list")
    if not timeline:
        return {}
    data = _object(timeline[0], "GDELT DOC series").get("data")
    if not isinstance(data, list):
        raise ValueError("GDELT DOC series data must be a list")
    points: dict[datetime, tuple[str, str | None]] = {}
    for raw in data:
        point = _object(raw, "GDELT DOC point")
        observed = datetime.strptime(str(point["date"]), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        if observed.time() != time.min:
            raise ValueError("GDELT DOC timeline must have daily resolution")
        if observed in points:
            raise ValueError("GDELT DOC timeline repeats a day")
        total = point.get("norm")
        points[observed] = (
            _decimal(str(point["value"])),
            None if total is None else _decimal(str(total)),
        )
    return points


def _parse_provider_time(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    if "." in normalized:
        prefix, suffix = normalized.split(".", maxsplit=1)
        fraction, offset = suffix.split("+", maxsplit=1)
        normalized = f"{prefix}.{fraction[:6].ljust(6, '0')}+{offset}"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("provider timestamp must include a timezone")
    return parsed.astimezone(UTC)


def _decimal(value: str) -> str:
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("provider value is not a decimal") from exc
    if not parsed.is_finite():
        raise ValueError("provider value must be finite")
    return "0" if parsed == 0 else format(parsed.normalize(), "f")


def _nonnegative_integer(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise ValueError("provider count cannot be negative")
    return parsed


def _dates(start: date, end: date) -> Sequence[date]:
    return tuple(start + timedelta(days=offset) for offset in range((end - start).days + 1))


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return cast(dict[str, object], value)
