"""Download snapshots of the ClinicalTrials.gov API reference into docs/ctgov/.

The search planner's prompt is built from these files, so the agent always sees
the same, official reference. The API is versioned and changes rarely; rerun this
when it does and review the diff.

    uv run python scripts/refresh_ctgov_docs.py
"""

import json
import urllib.request
from pathlib import Path

API = "https://clinicaltrials.gov/api"
OUT = Path(__file__).resolve().parent.parent / "docs" / "ctgov"

SNAPSHOTS = {
    "openapi.yaml": f"{API}/oas/v2",  # full OpenAPI spec
    "search-areas.json": f"{API}/v2/studies/search-areas",  # what each query.* parameter searches
    "enums.json": f"{API}/v2/studies/enums",  # allowed values for enum fields
    "metadata.json": f"{API}/v2/studies/metadata",  # every field ("piece") name, for AREA[...]
    "version.json": f"{API}/v2/version",
}


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "cheiron-docs-refresh"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, url in SNAPSHOTS.items():
        body = fetch(url)
        if name.endswith(".json"):  # pretty-print so diffs are readable
            body = (json.dumps(json.loads(body), indent=2, ensure_ascii=False) + "\n").encode()
        (OUT / name).write_bytes(body)
        print(f"{name:20} {len(body):>9,} bytes  <- {url}")


if __name__ == "__main__":
    main()
