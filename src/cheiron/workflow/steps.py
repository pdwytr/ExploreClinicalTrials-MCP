"""The five steps of the workflow, as interfaces. Implementations come later;
tests plug in fakes. Agents are async because they call an LLM; the source is
async because it calls the ClinicalTrials.gov API."""

from collections.abc import Callable
from typing import Protocol

from cheiron.fetch.models import DataVersion, StudySearchParams, Trial
from cheiron.models.request import QueryRequest
from cheiron.models.response import ChartVisualization, NetworkVisualization
from cheiron.workflow.plans import ChartPlan, DataProfile, FetchResult, SearchPlan


class SearchPlanner(Protocol):
    """Agent 1: question -> which API searches to run.

    Its LLM answers with SearchPlannerOutput; an Unanswerable answer is raised as
    UnsupportedQuery, so the workflow only ever receives a valid SearchPlan.
    `feedback` explains why the previous plan failed (API error, no results)."""

    async def plan(self, request: QueryRequest, feedback: list[str] | None = None) -> SearchPlan: ...


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


class Profiler(Protocol):
    """Code: summarizes fetched trials for the chart planner."""

    def profile(self, trials_by_group: dict[str, list[Trial]], total_matched: int) -> DataProfile: ...


class ChartPlanner(Protocol):
    """Agent 2: question + data profile -> how to show it."""

    async def plan(self, request: QueryRequest, search: SearchPlan, profile: DataProfile) -> ChartPlan: ...


class Visualizer(Protocol):
    """Code: aggregates trials per the chart plan into a visualization with citations."""

    def build(
        self, trials_by_group: dict[str, list[Trial]], plan: ChartPlan
    ) -> ChartVisualization | NetworkVisualization: ...
