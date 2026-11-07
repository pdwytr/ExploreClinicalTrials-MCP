"""Query outputs on disk: one folder per (question, data refresh).

    data/queries/<key>/
        request.json        the request
        plan.json           the planner's searches + rationale
        searches.json       searches as executed (with user filters), totals, trial files
        trials/<label>.json every fetched trial for one search
        meta.json           status, data version, warnings, timings, error

key = sha256(normalised request + data refresh timestamp). The registry refreshes daily, so
the same question on the same data always maps to the same folder, and a successful folder
is reused as the answer: same question + same data = same output.
"""

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from cheiron.models.request import QueryRequest
from cheiron.settings import PROJECT_ROOT
from cheiron.workflow.pipeline import FetchOutcome

DEFAULT_ROOT = PROJECT_ROOT / "data" / "queries"


def query_key(request: QueryRequest, data_timestamp: datetime) -> str:
    """Case and extra whitespace in the question don't change the key; filters and the data refresh do."""
    data = request.model_dump(mode="json", exclude_none=True)
    data["query"] = " ".join(data["query"].split()).casefold()
    canonical = json.dumps({"request": data, "data_timestamp": data_timestamp.isoformat()}, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n")


class QueryOutputs:
    def __init__(self, root: Path = DEFAULT_ROOT):
        self.root = root

    def folder(self, key: str) -> Path:
        return self.root / key

    def is_complete(self, key: str) -> bool:
        """A folder counts as an answer only if its last run succeeded."""
        meta = self.folder(key) / "meta.json"
        return meta.exists() and json.loads(meta.read_text()).get("status") == "succeeded"

    def save(self, key: str, request: QueryRequest, outcome: FetchOutcome, meta: dict[str, Any]) -> Path:
        folder = self.folder(key)
        (folder / "trials").mkdir(parents=True, exist_ok=True)
        _write_json(folder / "request.json", request.model_dump(mode="json", exclude_none=True))
        _write_json(folder / "plan.json", outcome.plan.model_dump(mode="json"))
        searches = []
        for (label, params), result in zip(outcome.prepared, outcome.results):
            trials_file = f"trials/{re.sub(r'[^a-z0-9]+', '-', label.casefold()).strip('-') or 'search'}.json"
            _write_json(folder / trials_file, [t.model_dump(mode="json") for t in result.trials])
            searches.append(
                {
                    "label": label,
                    "params": params.search,
                    "total_matched": result.total_matched,
                    "trials_fetched": len(result.trials),
                    "trials_file": trials_file,
                }
            )
        _write_json(folder / "searches.json", searches)
        _write_json(folder / "meta.json", meta)  # last: its presence marks the folder complete
        return folder

    def relative(self, path: Path) -> str:
        try:
            return str(path.relative_to(PROJECT_ROOT))
        except ValueError:
            return str(path)
