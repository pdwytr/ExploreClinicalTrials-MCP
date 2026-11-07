"""Query outputs on disk: one folder per query, named by its task id (a UUID).

    data/queries/<task_id>/
        request.json        the request (written when the query starts)
        plan.json           the planner's searches + rationale
        searches.json       searches as executed (with user filters), totals, trial files
        trials/<n>-<label>.json   every fetched trial for one search
        meta.json           status, data version, warnings, timings, error (written at the end)
"""

import json
import re
from pathlib import Path
from typing import Any

from cheiron.models.request import QueryRequest
from cheiron.settings import PROJECT_ROOT
from cheiron.workflow.pipeline import FetchOutcome

DEFAULT_ROOT = PROJECT_ROOT / "data" / "queries"


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n")


class QueryOutputs:
    def __init__(self, root: Path = DEFAULT_ROOT):
        self.root = root

    def create(self, task_id: str, request: QueryRequest) -> Path:
        folder = self.root / task_id
        folder.mkdir(parents=True)
        _write_json(folder / "request.json", request.model_dump(mode="json", exclude_none=True))
        return folder

    def save_fetch(self, folder: Path, outcome: FetchOutcome) -> None:
        _write_json(folder / "plan.json", outcome.plan.model_dump(mode="json"))
        (folder / "trials").mkdir()
        searches = []
        for n, ((label, params), result) in enumerate(zip(outcome.prepared, outcome.results), start=1):
            trials_file = f"trials/{n}-{re.sub(r'[^a-z0-9]+', '-', label.casefold()).strip('-')}.json"
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

    def save_meta(self, folder: Path, meta: dict[str, Any]) -> None:
        _write_json(folder / "meta.json", meta)

    def relative(self, path: Path) -> str:
        try:
            return str(path.relative_to(PROJECT_ROOT))
        except ValueError:
            return str(path)
