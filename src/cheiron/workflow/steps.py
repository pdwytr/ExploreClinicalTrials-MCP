"""The workflow's two pluggable parts, as interfaces. Tests plug in fakes.

    TrialSource   code: talks to ClinicalTrials.gov (implemented by CtgovClient)
    QueryPlanner  the LLM agent: plans, fetches through the given function, chooses the chart
                  (implemented by QueryAgent)
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from cheiron.fetch.endpoints import FieldSizesStep, FieldValuesStep, RecordSizeStep, StudyStep
from cheiron.fetch.models import DataVersion, StudySearchParams
from cheiron.models.request import QueryRequest
from cheiron.workflow.plans import ChartPlan, DataProfile, FetchResult, SearchPlan, StatsResult

if TYPE_CHECKING:
    from cheiron.workflow.pipeline import FetchOutcome


class TrialSource(Protocol):
    """Code: runs one search against ClinicalTrials.gov, following every page
    (or up to `limit` when one is set). Raises InvalidSearch when the API rejects the search.
    `on_progress(fetched, total)` is called after each page."""

    async def search(
        self,
        params: StudySearchParams,
        limit: int | None = None,
        on_progress: Callable[[int, int | None], None] | None = None,
    ) -> FetchResult: ...

    async def data_version(self) -> DataVersion:
        """API release and data refresh time (GET /version)."""
        ...

    async def fetch_study(self, step: StudyStep) -> FetchResult:
        """One trial by NCT number. Raises InvalidSearch if it does not exist."""
        ...

    async def fetch_stats(self, step: FieldValuesStep | FieldSizesStep | RecordSizeStep) -> StatsResult:
        """A registry-wide /stats call, validated against its response schema."""
        ...


@dataclass
class AgentResult:
    """What the agent hands back: its chart plan and the data it was chosen from."""

    chart: ChartPlan
    outcome: "FetchOutcome"
    profile: DataProfile
    chart_warnings: list[str]
    skills_loaded: list[str]
    references_read: list[str]
    usage: Any = None


class QueryPlanner(Protocol):
    """The agent. `fetch` executes a plan in code (user filters, every page) and returns the data;
    raises UnsupportedQuery if the question cannot be answered from registry data."""

    async def decide(self, request: QueryRequest, fetch: Callable[[SearchPlan], Awaitable["FetchOutcome"]]) -> AgentResult: ...
