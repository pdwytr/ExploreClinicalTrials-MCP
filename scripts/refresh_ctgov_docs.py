"""Download snapshots of the ClinicalTrials.gov API reference into docs/ctgov/.

The agent reads the live reference, loaded when the service starts (agents/api_docs.py).
These snapshots are its fallback when the API cannot be reached, and what tests run
against. Rerun this after the evals pass on a new API version, and review the diff.

    uv run python scripts/refresh_ctgov_docs.py           # download fresh snapshots
    uv run python scripts/refresh_ctgov_docs.py --check   # only check: exit 1 if the API version changed
"""

import json
import sys
import urllib.request
from pathlib import Path

API = "https://clinicaltrials.gov/api"
OUT = Path(__file__).resolve().parent.parent / "docs" / "ctgov"

SNAPSHOTS = {
    "openapi.yaml": f"{API}/oas/v2",  # full OpenAPI spec
    "search-areas.json": f"{API}/v2/studies/search-areas",  # what each query.* parameter searches
    "enums.json": f"{API}/v2/studies/enums",  # allowed values for enum fields
    # every field ("piece"), including search-only ones (counters, year fields), for AREA[...]
    "metadata.json": f"{API}/v2/studies/metadata?includeIndexedOnly=true",
    "version.json": f"{API}/v2/version",
}


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "studytrials-docs-refresh"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def check() -> int:
    """Compare the live API version with the stored snapshot. Exit code 1 if they differ (for CI)."""
    live = json.loads(fetch(SNAPSHOTS["version.json"]))["apiVersion"]
    stored = json.loads((OUT / "version.json").read_text())["apiVersion"]
    if live == stored:
        print(f"OK: docs/ctgov matches the live API ({live}).")
        return 0
    print(
        f"OUTDATED: live API is {live}, docs/ctgov describes {stored}.\n"
        "Rerun the evals on the new version, then scripts/refresh_ctgov_docs.py; re-capture "
        "essie-syntax.md if the page changed, update SNAPSHOT_API_VERSION, and review the diff."
    )
    return 1


def main() -> None:
    if "--check" in sys.argv[1:]:
        sys.exit(check())
    OUT.mkdir(parents=True, exist_ok=True)
    for name, url in SNAPSHOTS.items():
        body = fetch(url)
        if name.endswith(".json"):  # pretty-print so diffs are readable
            body = (json.dumps(json.loads(body), indent=2, ensure_ascii=False) + "\n").encode()
        (OUT / name).write_bytes(body)
        print(f"{name:20} {len(body):>9,} bytes  <- {url}")


if __name__ == "__main__":
    main()
