from __future__ import annotations

import json
from pathlib import Path

from server.app.main import create_app


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    destination = root / "openapi" / "openapi.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(destination)


if __name__ == "__main__":
    main()
