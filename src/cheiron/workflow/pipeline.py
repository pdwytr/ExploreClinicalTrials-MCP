"""The query workflow: request in, one visualization out.

    1. Search planner (agent)   request (all fields) -> SearchPlan (API searches it wrote)
    2. Add user filters (code)  structured fields AND-ed onto every search
    3. Fetch (code)             one search per side, in parallel
       -> API error or no results: feedback to the planner, one retry
    4. Profile (code)           trials              -> DataProfile
    5. Chart planner (agent)    request + profile   -> ChartPlan
    6. Check the chart plan     against what was fetched
    7. Visualize (code)         trials + ChartPlan  -> visualization with citations
    8. Assemble                 visualization + meta -> QueryResponse
"""

import asyncio
from dataclasses import dataclass

from cheiron.models.request import QueryRequest
from cheiron.models.response import Meta, QueryResponse
from cheiron.workflow.errors import InvalidSearch, NoResults, UnsupportedQuery
from cheiron.workflow.plans import ChartPlan, DataProfile, Dimension, FetchResult, SearchPlan
from cheiron.workflow.steps import ChartPlanner, Profiler, SearchPlanner, TrialSource, Visualizer
from cheiron.workflow.translate import PreparedSearch, apply_request_filters, filters_summary

MISSING_WARNING_SHARE = 0.10  # warn when more than 10% of trials lack the plotted value
PLANNING_ATTEMPTS = 2  # first plan + one retry with feedback


@dataclass
class QueryWorkflow:
    search_planner: SearchPlanner
    source: TrialSource
    profiler: Profiler
    chart_planner: ChartPlanner
    visualizer: Visualizer
    max_trials_per_search: int = 5000

    async def run(self, request: QueryRequest) -> QueryResponse:
        # 1-3. Plan, add user filters, fetch (with one feedback round)
        search, prepared, results, warnings = await self._plan_and_fetch(request)
        trials_by_group = {label: r.trials for (label, _), r in zip(prepared, results)}
        total_matched = sum(r.total_matched for r in results)
        trials_fetched = sum(len(t) for t in trials_by_group.values())
        for (label, _), result in zip(prepared, results):
            if result.truncated:
                warnings.append(f"{label}: analyzed {len(result.trials)} of {result.total_matched} matching trials.")
            if not result.trials and search.is_comparison:
                warnings.append(f"{label}: no matching trials.")

        # 4-6. How to show it
        profile = self.profiler.profile(trials_by_group, total_matched)
        chart = await self.chart_planner.plan(request, search, profile)
        warnings += check_chart_plan(chart, search, profile)

        # 7-8. Build and assemble
        visualization = self.visualizer.build(trials_by_group, chart)
        meta = Meta(
            interpretation=search.rationale,
            filters_applied=filters_summary(prepared),
            warnings=warnings,
            total_trials_matched=total_matched,
            trials_analyzed=trials_fetched,
            units={"trial_count": "trials"},
        )
        return QueryResponse(visualization=visualization, meta=meta)

    async def _plan_and_fetch(
        self, request: QueryRequest
    ) -> tuple[SearchPlan, list[PreparedSearch], list[FetchResult], list[str]]:
        feedback: list[str] | None = None
        for attempt in range(1, PLANNING_ATTEMPTS + 1):
            search = await self.search_planner.plan(request, feedback)
            prepared, warnings = apply_request_filters(search, request)
            try:
                results = await asyncio.gather(
                    *(self.source.search(params, self.max_trials_per_search) for _, params in prepared)
                )
            except InvalidSearch as exc:
                if attempt == PLANNING_ATTEMPTS:
                    raise
                feedback = [f"The API rejected a search: {exc.message}"]
                continue
            if any(r.total_matched for r in results):
                return search, prepared, list(results), warnings
            if attempt == PLANNING_ATTEMPTS:
                raise NoResults("No trials matched the search.", filters_summary(prepared))
            feedback = [f"No trials matched these searches: {filters_summary(prepared)['searches']}"]
        raise AssertionError("unreachable")


def check_chart_plan(chart: ChartPlan, search: SearchPlan, profile: DataProfile) -> list[str]:
    """Reject plans the data cannot support; return warnings for weak ones."""
    used = [d for d in (chart.x, chart.series) if d is not None]
    if Dimension.GROUP in used and not search.is_comparison:
        raise UnsupportedQuery("The chart groups by comparison side, but there is only one search.")

    warnings = []
    for dim in used:
        if dim is Dimension.GROUP:
            continue
        field = profile.fields.get(dim)
        if field is None or field.missing == profile.trials_fetched:
            raise UnsupportedQuery(f"No fetched trial has a value for {dim.value}.")
        if field.missing > MISSING_WARNING_SHARE * profile.trials_fetched:
            warnings.append(f"{field.missing} of {profile.trials_fetched} trials have no {dim.value} and are excluded.")
    return warnings
