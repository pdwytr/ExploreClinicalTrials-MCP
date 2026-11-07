"""The five steps of the workflow, as interfaces. Implementations come later;
tests plug in fakes. Agents are async because they call an LLM; the source is
async because it calls the ClinicalTrials.gov API."""

from typing import Protocol

from cheiron.fetch.models import StudySearchParams, Trial
from cheiron.models.request import QueryRequest
from cheiron.models.response import ChartVisualization, NetworkVisualization
from cheiron.workflow.plans import ChartPlan, DataProfile, FetchResult, SearchPlan


class SearchPlanner(Protocol):
    """Agent 1: question -> what to search for."""

    async def plan(self, request: QueryRequest) -> SearchPlan: ...


class TrialSource(Protocol):
    """Code: runs one search against ClinicalTrials.gov, following pages up to `limit`."""

    async def search(self, params: StudySearchParams, limit: int) -> FetchResult: ...


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
