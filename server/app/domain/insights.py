from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

InsightTopic = Literal["savings", "budgets", "obligations", "crypto", "general"]
InsightMode = Literal["local-model", "template-fallback", "refusal"]
NotificationSeverity = Literal["info", "warning", "urgent"]


@dataclass(frozen=True)
class AuthorizedFact:
    fact_id: str
    topic: InsightTopic
    statement: str
    source_kind: str
    source_ids: tuple[str, ...]
    as_of_utc: datetime | None

    def __post_init__(self) -> None:
        if not self.fact_id or not self.statement or not self.source_kind:
            raise ValueError("authorized facts require an ID, statement, and source kind")
        if self.as_of_utc is not None and self.as_of_utc.tzinfo is None:
            raise ValueError("fact timestamps must be timezone-aware")


@dataclass(frozen=True)
class AuthorizedFactBundle:
    bundle_id: str
    month: str
    facts: tuple[AuthorizedFact, ...]

    @classmethod
    def build(
        cls,
        *,
        actor_address: str,
        month: str,
        facts: tuple[AuthorizedFact, ...],
    ) -> AuthorizedFactBundle:
        payload = {
            "actor_address": actor_address.lower(),
            "month": month,
            "facts": [
                {
                    "fact_id": fact.fact_id,
                    "topic": fact.topic,
                    "statement": fact.statement,
                    "source_kind": fact.source_kind,
                    "source_ids": list(fact.source_ids),
                    "as_of_utc": (
                        fact.as_of_utc.astimezone(UTC).isoformat()
                        if fact.as_of_utc is not None
                        else None
                    ),
                }
                for fact in facts
            ],
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return cls(bundle_id=f"facts_{digest}", month=month, facts=facts)

    def by_id(self) -> dict[str, AuthorizedFact]:
        return {fact.fact_id: fact for fact in self.facts}


@dataclass(frozen=True)
class FactSelection:
    fact_ids: tuple[str, ...]
    confidence: float

    def __post_init__(self) -> None:
        if not 0 <= self.confidence <= 1:
            raise ValueError("selection confidence must be between zero and one")


@dataclass(frozen=True)
class InsightNotification:
    notification_id: str
    severity: NotificationSeverity
    title: str
    message: str
    href: Literal["/finance", "/groups", "/crypto", "/insights"]
    fact_ids: tuple[str, ...]


@dataclass(frozen=True)
class InsightResponse:
    summary: str
    evidence: tuple[AuthorizedFact, ...]
    caveats: tuple[str, ...]
    follow_up_questions: tuple[str, ...]
    mode: InsightMode
    model_id: str
    model_revision: str
    refused: bool


@dataclass(frozen=True)
class InsightsOverview:
    bundle: AuthorizedFactBundle
    response: InsightResponse
    notifications: tuple[InsightNotification, ...]
