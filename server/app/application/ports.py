from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ImmutableStoreResult:
    key: str
    record_id: str
    deduplicated: bool


class KeyValueStore(Protocol):
    def get(self, key: str) -> str | None: ...

    def put(self, key: str, value: str) -> None: ...

    def range_values(self, prefix: str) -> Sequence[str]: ...
