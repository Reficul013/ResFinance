from __future__ import annotations

import copy
import hashlib
import json
import random
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import cast

import pytest
import torch

from ml.data.datasets import build_sequence_dataset, requires_market_only_fallback
from ml.data.synthetic import generate_synthetic_feature_dataset
from ml.evaluation.prospective import GateCriteria, gate_decision, ledger_entry, score_ledger
from ml.features.point_in_time import FeatureDataset
from ml.models.mspciformer import FusionMode, ThreeAssetMSPCIFormer
from ml.runs.checkpoints import restore_models
from ml.runs.forward import (
    ForwardResearchResult,
    ProspectiveRunConfig,
    infer_current_forecast,
    run_forward_research,
    standardizer_from_artifact,
)
from scripts.milestone9.run_forward_completion import make_snapshot
from scripts.milestone9.run_prospective import forecast_entry, ingest_latest, stored_result
from server.app.domain.crypto import CryptoAsset, ObservationChannel
from server.app.infrastructure.blob_repository import EncryptedBlobRepository
from server.app.infrastructure.crypto_repository import CryptoResearchRepository
from server.app.infrastructure.encryption import AesGcmCipher, canonical_json_bytes
from server.app.infrastructure.portfolio_repository import PortfolioResearchRepository
from server.app.infrastructure.prospective_repository import ProspectiveLedgerRepository
from server.app.infrastructure.provider_adapters import GdeltDocTimelineAdapter, JsonResponse
from server.app.infrastructure.research_repository import PromotionCriteria, ResearchRunRepository

FROZEN_AT = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
RUN_ID = "prospective-protocol-test"


class MemoryKeyValueStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def put(self, key: str, value: str) -> None:
        self.values[key] = value

    def range_values(self, prefix: str) -> Sequence[str]:
        return [self.values[key] for key in sorted(self.values) if key.startswith(prefix)]


def _v3_dataset(dataset: FeatureDataset) -> FeatureDataset:
    providers = ["coin-metrics", "defillama", "gdelt-doc"]
    return FeatureDataset(
        dataset.dataset_hash, dataset.rows, {**dataset.manifest, "providers": providers}
    )


@pytest.fixture(scope="module")
def prospective_run() -> tuple[FeatureDataset, ForwardResearchResult]:
    # Decision dates 2024-05-01 to 2026-11-16 cover the frozen windows and three weeks after.
    dataset = _v3_dataset(generate_synthetic_feature_dataset(day_count=930, start=date(2024, 5, 1)))
    result = run_forward_research(
        dataset,
        config=ProspectiveRunConfig(epochs=1),
        run_id=RUN_ID,
        clock=lambda: FROZEN_AT,
    )
    return dataset, result


def _repositories() -> tuple[
    MemoryKeyValueStore, ResearchRunRepository, ProspectiveLedgerRepository
]:
    store = MemoryKeyValueStore()
    research = ResearchRunRepository(
        store, EncryptedBlobRepository(store, AesGcmCipher(b"p" * 32, key_id="prospective-test"))
    )
    return store, research, ProspectiveLedgerRepository(store, research)


def _through(dataset: FeatureDataset, decision_date: date) -> FeatureDataset:
    rows = tuple(
        row for row in dataset.rows if str(row["timestamp_utc"])[:10] <= decision_date.isoformat()
    )
    return FeatureDataset(dataset.dataset_hash, rows, dataset.manifest)


def _entry(
    dataset: FeatureDataset,
    result: ForwardResearchResult,
    decision_date: date,
    *,
    hours_late: float = 6,
) -> dict[str, object]:
    decision_time = datetime.combine(decision_date + timedelta(days=1), time.min, tzinfo=UTC)
    return forecast_entry(
        _through(dataset, decision_date),
        result,
        issued_at_utc=decision_time + timedelta(hours=hours_late),
    )


def test_prospective_run_freezes_per_path_calibration_without_a_holdout(
    prospective_run: tuple[FeatureDataset, ForwardResearchResult],
) -> None:
    dataset, result = prospective_run
    manifest = result.manifest
    window = cast(dict[str, object], manifest["prospective"])
    calibration = cast(dict[str, object], manifest["adaptive_calibration"])

    assert manifest["schema_version"] == 4
    assert manifest["evaluation_protocol"] == "prospective-forward-v3"
    assert "forward_holdout" not in manifest
    assert window["training_end"] == "2025-08-21"
    assert window["validation_start"] == "2025-09-21"
    assert window["validation_end"] == "2026-09-20"
    assert window["prospective_start"] == "2026-10-28"
    assert window["retrospective_holdout"] is None
    assert window["news_provider"] == "gdelt-doc"
    assert window["promotion_gate"] == "forecast-promotion-prospective-v1"
    assert window["post_freeze_tuning_permitted"] is False

    sequences = build_sequence_dataset(dataset, horizons=(15, 20, 30))
    validation = [
        index
        for index, value in enumerate(sequences.decision_dates)
        if "2025-09-21" <= value[:10] <= "2026-09-20"
    ]
    stale = requires_market_only_fallback(sequences.masks[validation])
    counts = cast(dict[str, int], calibration["path_calibration_sample_counts"])
    paths = cast(dict[str, list[float]], calibration["path_adjustments"])
    assert calibration["schema_version"] == 3
    assert counts == {"primary": int((~stale).sum()), "fallback": len(validation)}
    assert 0 < counts["primary"] < counts["fallback"]
    assert set(paths) == {"primary", "fallback"}
    assert all(len(values) == 3 and min(values) >= 0 for values in paths.values())
    assert len(cast(list[float], calibration["no_change_adjustment"])) == 3
    metrics = cast(dict[str, dict[str, object]], manifest["metrics"])
    assert metrics["adaptive-gating"]["sample_count"] == window["validation_sample_count"]
    rows = json.loads(result.artifacts["predictions.json"])
    assert {row["protocol"] for row in rows} == {"prospective-forward-v3"}


def test_schema_v4_runs_persist_but_cannot_use_the_manifest_metric_gate(
    prospective_run: tuple[FeatureDataset, ForwardResearchResult],
) -> None:
    _, result = prospective_run
    _, research, _ = _repositories()
    research.put_completed_run(result.manifest, result.artifacts)

    with pytest.raises(ValueError, match="only from a passing prospective gate"):
        research.promote_model(
            run_id=RUN_ID,
            model_name="adaptive-gating",
            criteria=PromotionCriteria(),
            promoted_at_utc=FROZEN_AT,
            approved_by="test",
        )
    with pytest.raises(ValueError, match="has not reached a decision"):
        research.promote_prospective(run_id=RUN_ID, promoted_at_utc=FROZEN_AT, approved_by="test")


@pytest.mark.parametrize(
    ("section", "field", "value", "message"),
    [
        ("prospective", "news_provider", "gdelt", "prospective forward protocol v3"),
        ("prospective", "retrospective_holdout", "2025-04-01", "prospective forward protocol v3"),
        ("prospective", "embargo_days", 15, "prospective forward protocol v3"),
        ("prospective", "prospective_start", "2026-10-01", "prospective forward protocol v3"),
        ("prospective", "horizons", [1, 3, 5], "prospective forward protocol v3"),
        ("adaptive_calibration", "path_adjustments", None, "per-path calibration"),
        ("adaptive_calibration", "no_change_adjustment", [-0.1, 0.1, 0.1], "per-path calibration"),
    ],
)
def test_schema_v4_manifest_tampering_is_rejected(
    prospective_run: tuple[FeatureDataset, ForwardResearchResult],
    section: str,
    field: str,
    value: object,
    message: str,
) -> None:
    _, result = prospective_run
    manifest = copy.deepcopy(result.manifest)
    cast(dict[str, object], manifest[section])[field] = value
    _, research, _ = _repositories()

    with pytest.raises(ValueError, match=message):
        research.put_completed_run(manifest, result.artifacts)


def test_prospective_run_rejects_gkg_news_and_thin_primary_calibration() -> None:
    dataset = generate_synthetic_feature_dataset(day_count=930, start=date(2024, 5, 1))
    gkg = FeatureDataset(
        dataset.dataset_hash,
        dataset.rows,
        {**dataset.manifest, "providers": ["coin-metrics", "defillama", "gdelt", "gdelt-doc"]},
    )

    with pytest.raises(ValueError, match="GDELT DOC news provider only"):
        run_forward_research(gkg, config=ProspectiveRunConfig(epochs=1))
    with pytest.raises(ValueError, match="too few fresh-source validation samples"):
        run_forward_research(
            _v3_dataset(dataset),
            config=ProspectiveRunConfig(epochs=1, minimum_primary_calibration_samples=10**6),
        )


def test_each_serving_path_uses_its_own_range_adjustment(
    prospective_run: tuple[FeatureDataset, ForwardResearchResult],
) -> None:
    dataset, result = prospective_run
    manifest = result.manifest
    primary, _ = restore_models(
        lambda: ThreeAssetMSPCIFormer(fusion_mode=FusionMode.ADAPTIVE, horizon_count=3),
        result.artifacts[str(manifest["deployment_model_artifact"])],
    )
    fallback, _ = restore_models(
        lambda: ThreeAssetMSPCIFormer(fusion_mode=FusionMode.MARKET_ONLY, horizon_count=3),
        result.artifacts[str(manifest["fallback_model_artifact"])],
    )
    standardizer = standardizer_from_artifact(
        result.artifacts[str(manifest["standardizer_artifact"])]
    )
    latest = max(str(row["timestamp_utc"]) for row in dataset.rows)
    rows = []
    for row in dataset.rows:
        if row["asset"] == "ETH" and row["timestamp_utc"] == latest:
            masks = {**cast(dict[str, bool], row["availability_masks"])}
            for name in masks:
                if name.startswith("sentiment_"):
                    masks[name] = False
            row = {**row, "availability_masks": masks}
        rows.append(row)
    stale_eth = FeatureDataset(dataset.dataset_hash, tuple(rows), dataset.manifest)

    def widths(primary_adjustment: float, fallback_adjustment: float) -> torch.Tensor:
        calibration = copy.deepcopy(cast(dict[str, object], manifest["adaptive_calibration"]))
        calibration["path_adjustments"] = {
            "primary": [primary_adjustment] * 3,
            "fallback": [fallback_adjustment] * 3,
        }
        current = infer_current_forecast(
            stale_eth,
            model=primary,
            standardizer=standardizer,
            calibration=calibration,
            fallback_model=fallback,
        )
        assert current.fallback_used == (False, True, False)
        assert torch.equal(current.expected, torch.zeros_like(current.expected))
        return current.p90 - current.p10

    # Adjustments of at least one keep p10 and p90 clear of the median clamp.
    base = widths(1.0, 1.0)
    widened_fallback = widths(1.0, 1.5)
    widened_primary = widths(1.25, 1.0)
    assert torch.allclose(widened_fallback[1] - base[1], torch.full((3,), 1.0))
    assert torch.allclose(widened_fallback[[0, 2]], base[[0, 2]])
    assert torch.allclose(widened_primary[[0, 2]] - base[[0, 2]], torch.full((2, 3), 0.5))
    assert torch.allclose(widened_primary[1], base[1])


def test_ledger_accepts_only_on_time_entries_for_the_frozen_run(
    prospective_run: tuple[FeatureDataset, ForwardResearchResult],
) -> None:
    dataset, result = prospective_run
    _, research, ledger = _repositories()
    research.put_completed_run(result.manifest, result.artifacts)
    first = _entry(dataset, result, date(2026, 10, 28))

    stored = ledger.put_entry(first)
    assert not stored.deduplicated
    assert ledger.put_entry(first).deduplicated
    assert ledger.has_entry(RUN_ID, date(2026, 10, 28))
    assert first["decision_time_utc"] == "2026-10-29T00:00:00Z"
    assert len(cast(list[object], first["forecasts"])) == 18
    with pytest.raises(ValueError, match="already recorded"):
        ledger.put_entry(_entry(dataset, result, date(2026, 10, 28), hours_late=7))
    with pytest.raises(ValueError, match="late forecast"):
        ledger.put_entry(_entry(dataset, result, date(2026, 10, 30), hours_late=25))
    with pytest.raises(ValueError, match="before its decision time"):
        ledger.put_entry(_entry(dataset, result, date(2026, 10, 30), hours_late=-1))
    with pytest.raises(ValueError, match="precedes the prospective window"):
        ledger.put_entry(_entry(dataset, result, date(2026, 10, 27)))
    tampered = copy.deepcopy(first)
    cast(list[dict[str, object]], tampered["forecasts"])[0]["p10"] = -0.99
    with pytest.raises(ValueError, match="hash does not match"):
        ledger.put_entry(tampered)
    foreign = _entry(dataset, result, date(2026, 10, 31))
    foreign["model_hashes"] = {"deployment": "0" * 64, "fallback": "1" * 64}
    foreign["entry_hash"] = hashlib.sha256(
        canonical_json_bytes({key: value for key, value in foreign.items() if key != "entry_hash"})
    ).hexdigest()
    with pytest.raises(ValueError, match="does not match its frozen run"):
        ledger.put_entry(foreign)
    assert [entry["decision_date"] for entry in ledger.entries(RUN_ID)] == ["2026-10-28"]


def _synthetic_ledger(
    days: int, *, half_width: dict[int, float] | None = None, seed: int = 5
) -> tuple[list[dict[str, object]], dict[tuple[str, date], float]]:
    """Ledger over random-walk prices; without ``half_width`` each horizon's symmetric range
    covers 80% of the first 90 decision dates' outcomes."""
    generator = random.Random(seed)
    start = date(2026, 10, 28)
    prices: dict[tuple[str, date], float] = {}
    for asset in ("BTC", "ETH", "SOL"):
        price = 100.0
        for offset in range(days + 40):
            prices[(asset, start + timedelta(days=offset))] = price
            price *= 1 + generator.gauss(0, 0.03)
    if half_width is None:
        half_width = {}
        for horizon in (15, 20, 30):
            moves = sorted(
                abs(
                    prices[(asset, start + timedelta(days=offset + horizon))]
                    / prices[(asset, start + timedelta(days=offset))]
                    - 1
                )
                for asset in ("BTC", "ETH", "SOL")
                for offset in range(90)
            )
            half_width[horizon] = moves[int(0.8 * len(moves))]
    entries = []
    for offset in range(days):
        widths = torch.tensor([[half_width[15], half_width[20], half_width[30]]] * 3)
        decision = start + timedelta(days=offset)
        entries.append(
            ledger_entry(
                run_id="synthetic",
                protocol="prospective-forward-v3",
                decision_time_utc=f"{(decision + timedelta(days=1)).isoformat()}T00:00:00Z",
                issued_at_utc=datetime.combine(decision + timedelta(days=1), time(6), tzinfo=UTC),
                horizons=(15, 20, 30),
                expected=torch.zeros(3, 3),
                probability_up=torch.full((3, 3), 0.5),
                p10=-widths,
                p50=torch.zeros(3, 3),
                p90=widths,
                fallback_used=(False, offset % 2 == 0, False),
                no_change_adjustment=(0.6, 0.7, 0.8),
                model_hashes={"deployment": "a" * 64, "fallback": "b" * 64},
                calibration_hash="c" * 64,
                dataset_hash="d" * 64,
            )
        )
    return entries, prices


def test_gate_waits_for_ninety_scored_dates_and_ignores_later_entries() -> None:
    entries, prices = _synthetic_ledger(130)

    early = score_ledger(entries[:89], prices)
    decided = score_ledger(entries[:90], prices)
    later = score_ledger(entries, prices)

    assert cast(dict[str, object], early["gate"])["status"] == "insufficient-data"
    gate = cast(dict[str, object], decided["gate"])
    assert gate["status"] == "passed", gate["checks"]
    assert gate_decision("synthetic", decided) == gate_decision("synthetic", later)
    horizon = cast(dict[str, dict[str, object]], later["horizons"])["15"]
    assert horizon["scored_decision_dates"] == 130
    assert cast(dict[str, int], horizon["gate_sample"])["first_decision_date"] == "2026-10-28"
    # ETH (one asset in three) uses the fallback on every other decision date.
    assert later["fallback_share"] == pytest.approx(1 / 6)

    narrow, prices = _synthetic_ledger(90, half_width={15: 0.001, 20: 0.001, 30: 0.001})
    failed = cast(dict[str, object], score_ledger(narrow, prices)["gate"])
    assert failed["status"] == "failed"
    assert cast(dict[str, bool], failed["checks"])["coverage_15d"] is False

    missing_outcome = dict(prices)
    del missing_outcome[("SOL", date(2026, 10, 28) + timedelta(days=30))]
    assert cast(dict[str, object], score_ledger(narrow, missing_outcome)["gate"])["status"] == (
        "insufficient-data"
    )
    short = score_ledger(entries, prices, criteria=GateCriteria(sample_decision_dates=10))
    assert cast(dict[str, int], short["criteria"])["sample_decision_dates"] == 10


def test_gate_decision_is_recorded_once_and_alone_permits_promotion(
    prospective_run: tuple[FeatureDataset, ForwardResearchResult],
) -> None:
    dataset, result = prospective_run
    store, research, ledger = _repositories()
    research.put_completed_run(result.manifest, result.artifacts)
    for offset in range(3):
        ledger.put_entry(_entry(dataset, result, date(2026, 10, 28) + timedelta(days=offset)))
    entries = ledger.entries(RUN_ID)
    prices = {
        (str(row["asset"]), date.fromisoformat(str(row["timestamp_utc"])[:10])): float(
            str(cast(dict[str, object], row["values"])["market_price_usd"])
        )
        for row in dataset.rows
    }
    interim = score_ledger(entries, prices)
    assert cast(dict[str, object], interim["gate"])["status"] == "insufficient-data"
    assert (
        cast(dict[str, dict[str, object]], interim["horizons"])["15"]["scored_decision_dates"] == 3
    )

    def decision(status: str, hashes: list[str] | None = None) -> dict[str, object]:
        scorecard = copy.deepcopy(interim)
        scorecard["gate"] = {
            "status": status,
            "checks": {"coverage_15d": status == "passed"},
            "pooled": {"deployable": {"count": 9}, "no-change": {"count": 9}},
            "entry_hashes": hashes or [str(entry["entry_hash"]) for entry in entries],
        }
        return gate_decision(RUN_ID, scorecard)

    with pytest.raises(ValueError, match="absent from the ledger"):
        ledger.put_gate_decision(decision("passed", ["e" * 64]))
    ledger.put_gate_decision(decision("passed"))
    assert ledger.put_gate_decision(decision("passed")).deduplicated
    with pytest.raises(ValueError, match="already recorded"):
        ledger.put_gate_decision(decision("failed"))

    promotion = research.promote_prospective(
        run_id=RUN_ID, promoted_at_utc=FROZEN_AT, approved_by="test-approver"
    )
    event = research.promotion_event(promotion.key.removeprefix("promotion:forecast:"))
    assert event["criteria"]["version"] == "forecast-promotion-prospective-v1"
    # Synthetic rows carry one provenance id; the snapshot cites it for each price.
    priced = FeatureDataset(
        dataset.dataset_hash,
        tuple(
            {
                **row,
                "source_record_ids": {
                    "market_price_usd": cast(dict[str, str], row["source_record_ids"])["synthetic"]
                },
            }
            for row in dataset.rows
        ),
        dataset.manifest,
    )
    snapshot, _ = make_snapshot(
        _through(priced, date(2026, 11, 1)),
        result=stored_result(research, RUN_ID),
        promotion_event_id=str(event["event_id"]),
    )
    PortfolioResearchRepository(store, research).put_forecast_snapshot(snapshot)
    assert snapshot.horizon_days == 15

    _, failed_research, failed_ledger = _repositories()
    failed_research.put_completed_run(result.manifest, result.artifacts)
    for entry in entries:
        failed_ledger.put_entry(entry)
    failed_ledger.put_gate_decision(decision("failed"))
    with pytest.raises(ValueError, match="prospective gate failed"):
        failed_research.promote_prospective(
            run_id=RUN_ID, promoted_at_utc=FROZEN_AT, approved_by="test-approver"
        )


def test_ingestion_resumes_each_source_after_its_newest_stored_day() -> None:
    store = MemoryKeyValueStore()
    crypto = CryptoResearchRepository(store)
    requests: list[str] = []

    def fetch(url: str) -> JsonResponse:
        requests.append(url)
        tone = "timelinetone" in url
        first = datetime(2026, 8, 1, tzinfo=UTC)
        data = [
            {
                "date": (first + timedelta(days=offset)).strftime("%Y%m%dT%H%M%SZ"),
                "value": "-0.5" if tone else "12",
                **({} if tone else {"norm": "150000"}),
            }
            for offset in range(80)
        ]
        return JsonResponse(
            url, datetime(2026, 10, 20, tzinfo=UTC), {"timeline": [{"data": data}]}, "f" * 64
        )

    class Unpublished:
        provider = "coin-metrics"
        adapter_id = "unpublished"
        supported_assets = frozenset(CryptoAsset)

        def observations(self, **_: object) -> Sequence[object]:
            raise RuntimeError("provider has not published")

    adapters = (
        (lambda: GdeltDocTimelineAdapter(fetcher=fetch), "gdelt-doc", ObservationChannel.SENTIMENT),
    )
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("scripts.milestone9.run_prospective.START", date(2026, 10, 1))
        first = ingest_latest(crypto, end=date(2026, 10, 10), adapters=adapters)
        second = ingest_latest(crypto, end=date(2026, 10, 18), adapters=adapters)
        third = ingest_latest(crypto, end=date(2026, 10, 18), adapters=adapters)
        broken = ingest_latest(
            crypto,
            end=date(2026, 10, 18),
            adapters=((Unpublished, "coin-metrics", ObservationChannel.MARKET), *adapters),
        )

    assert first[0]["status"] == "ingested" and first[0]["observation_count"] == 3 * 2 * 10
    assert second[0]["status"] == "ingested" and second[0]["observation_count"] == 3 * 2 * 8
    assert "startdatetime=20260913000000" in requests[6]
    assert third == [{"adapter": "gdelt-doc-timeline", "status": "up-to-date"}]
    assert broken == [
        {"adapter": "unpublished", "status": "failed", "error": "provider has not published"},
        {"adapter": "gdelt-doc-timeline", "status": "up-to-date"},
    ]
    days = {item.observed_at_utc.date() for item in crypto.observations()}
    assert min(days) == date(2026, 10, 1) and max(days) == date(2026, 10, 18)
    assert {item.asset for item in crypto.observations()} == set(CryptoAsset)
