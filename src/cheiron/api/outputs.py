"""Query outputs on disk: one folder per query, named by its task id (a UUID).

    data/queries/<task_id>/
        request.json        the request (written when the query starts)
        response.json       the QueryResponse returned to the client (visualization + meta + vega_lite)
        meta.json           status, data version, warnings, timings, error (written at the end)
        fetch-<n>/          one folder per fetch_data call the agent made, in order
            plan.json           the agent's steps + rationale for this fetch
            error.json          why the fetch failed (failed fetches only)
            steps.json          each step as executed (endpoint, params with user filters), totals, data file
            profile.json        what the agent saw about this data (code-computed counts)
            trials/<n>-<label>.json   trials from a /studies search or single-study lookup
            stats/<n>-<label>.json    a validated registry-wide /stats response
"""

import json
import re
from pathlib import Path
from typing import Any

from cheiron.models.request import QueryRequest
from cheiron.models.response import QueryResponse
from cheiron.settings import PROJECT_ROOT
from cheiron.workflow.pipeline import FetchOutcome
from cheiron.workflow.plans import DataProfile, SearchPlan, StatsResult
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

    def save_fetch(
        self,
        folder: Path,
        plan: SearchPlan,
        outcome: FetchOutcome | None,
        profile: DataProfile | None = None,
        error: str | None = None,
    ) -> None:
        """One fetch's folder: plan.json, then error.json or steps.json + profile.json + each step's data."""
        folder.mkdir(parents=True, exist_ok=True)
        _write_json(folder / "plan.json", plan.model_dump(mode="json"))
        if outcome is None:
            _write_json(folder / "error.json", {"error": error})
            return
        if profile is not None:
            _write_json(folder / "profile.json", profile.model_dump(mode="json", exclude_none=True))
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

    def save_response(self, folder: Path, response: QueryResponse) -> None:
        _write_json(folder / "response.json", response.model_dump(mode="json", by_alias=True))

    def save_meta(self, folder: Path, meta: dict[str, Any]) -> None:
        _write_json(folder / "meta.json", meta)

    def relative(self, path: Path) -> str:
        try:
            return str(path.relative_to(PROJECT_ROOT))
        except ValueError:
            return str(path)
