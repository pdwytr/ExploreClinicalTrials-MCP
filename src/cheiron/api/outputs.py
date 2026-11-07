"""Query outputs on disk: one folder per query, named by its task id (a UUID).

    data/queries/<task_id>/
        request.json        the request (written when the query starts)
        plan.json           the planner's steps + rationale
        steps.json          each step as executed (endpoint, params with user filters), totals, data file
        trials/<n>-<label>.json   trials from a /studies search or single-study lookup
        stats/<n>-<label>.json    a validated registry-wide /stats response
        meta.json           status, data version, warnings, timings, error (written at the end)
"""

import json
import re
from pathlib import Path
from typing import Any

from cheiron.models.request import QueryRequest
from cheiron.settings import PROJECT_ROOT
from cheiron.workflow.pipeline import FetchOutcome
from cheiron.workflow.plans import StatsResult
from cheiron.workflow.translate import step_summary

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
        """plan.json, steps.json, and each step's data: trials/<n>-<label>.json or stats/<n>-<label>.json."""
        _write_json(folder / "plan.json", outcome.plan.model_dump(mode="json"))
        steps = []
        for n, ((label, target), result) in enumerate(zip(outcome.prepared, outcome.results), start=1):
            name = f"{n}-{re.sub(r'[^a-z0-9]+', '-', label.casefold()).strip('-')}.json"
            entry = step_summary(label, target)
            if isinstance(result, StatsResult):
                (folder / "stats").mkdir(exist_ok=True)
                _write_json(folder / "stats" / name, result.data.model_dump(mode="json", by_alias=True))
                entry |= {"stats_file": f"stats/{name}", "incomplete_fields": result.incomplete_fields}
            else:
                (folder / "trials").mkdir(exist_ok=True)
                _write_json(folder / "trials" / name, [t.model_dump(mode="json") for t in result.trials])
                entry |= {
                    "total_matched": result.total_matched,
                    "trials_fetched": len(result.trials),
                    "trials_file": f"trials/{name}",
                }
            steps.append(entry)
        _write_json(folder / "steps.json", steps)

    def save_meta(self, folder: Path, meta: dict[str, Any]) -> None:
        _write_json(folder / "meta.json", meta)

    def relative(self, path: Path) -> str:
        try:
            return str(path.relative_to(PROJECT_ROOT))
        except ValueError:
            return str(path)
