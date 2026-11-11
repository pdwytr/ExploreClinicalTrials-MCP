"""Write the service's OpenAPI schema to docs/api/openapi.json (no server needed).

    uv run python scripts/export_openapi.py

The same schema is served live at /openapi.json, with interactive docs at /docs and /redoc.
A test fails if the committed file drifts from the code.
"""

import json
from pathlib import Path

from exploreclinicaltrials.api.app import create_app

OUT = Path(__file__).resolve().parent.parent / "docs" / "api" / "openapi.json"


def schema() -> dict:
    return create_app(lambda stack: None).openapi()


if __name__ == "__main__":
    OUT.write_text(json.dumps(schema(), indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {OUT}")
