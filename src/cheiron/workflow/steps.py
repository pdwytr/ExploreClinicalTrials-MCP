"""The workflow's two pluggable parts, as interfaces. Tests plug in fakes.

    TrialSource   code: talks to ClinicalTrials.gov (implemented by CtgovClient)
    QueryPlanner  the LLM agent: plans, fetches through the given function, chooses the chart
                  (implemented by QueryAgent)
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
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
class FetchRecord:
    """One fetch_data call: its plan, and either the data + profile or the error."""

    number: int
    plan: SearchPlan
    outcome: "FetchOutcome | None" = None
    profile: DataProfile | None = None
    error: str | None = None
    seconds: float | None = None  # how long the fetch took


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
    fetches: list[FetchRecord] = field(default_factory=list)  # every fetch, in order; the chart uses `outcome`
    messages: list = field(default_factory=list)  # the agent's message history, for the trace
    seconds: float = 0.0  # the agent run, fetches included


class QueryPlanner(Protocol):
    """The agent. `fetch` executes a plan in code (user filters, every page) and returns the data;
    raises UnsupportedQuery if the question cannot be answered from registry data."""

    async def decide(self, request: QueryRequest, fetch: Callable[[SearchPlan], Awaitable["FetchOutcome"]]) -> AgentResult: ...
