from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TypeVar

from server.app.domain.events import DomainEvent

ProjectionT = TypeVar("ProjectionT")


def rebuild_projection(
    events: Sequence[DomainEvent],
    *,
    initial: ProjectionT,
    reducer: Callable[[ProjectionT, DomainEvent], ProjectionT],
) -> ProjectionT:
    projection = initial
    expected_version = 1
    for event in events:
        if event.aggregate_version != expected_version:
            raise ValueError(
                "event stream is not contiguous: "
                f"expected version {expected_version}, got {event.aggregate_version}"
            )
        projection = reducer(projection, event)
        expected_version += 1
    return projection
