from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class KeyValueStore(Protocol):
    def get(self, key: str) -> str | None: ...

    def put(self, key: str, value: str) -> None: ...

    def range_values(self, prefix: str) -> Sequence[str]: ...
