"""The query workflow: request in, one visualization out.

    1. Search planner (agent)   request (all fields) -> SearchPlan
    2. Verify user filters      restore any structured field the planner dropped
    3. Fetch (code)             one search per group, in parallel
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
from cheiron.workflow.errors import NoResults, UnsupportedQuery
from cheiron.workflow.plans import ChartPlan, DataProfile, Dimension, SearchPlan
from cheiron.workflow.steps import ChartPlanner, Profiler, SearchPlanner, TrialSource, Visualizer
from cheiron.workflow.translate import enforce_request_filters, filters_summary, search_params_for

MISSING_WARNING_SHARE = 0.10  # warn when more than 10% of trials lack the plotted value


@dataclass
class QueryWorkflow:
    search_planner: SearchPlanner
    source: TrialSource
    profiler: Profiler
    chart_planner: ChartPlanner
    visualizer: Visualizer
    max_trials_per_group: int = 5000

    async def run(self, request: QueryRequest) -> QueryResponse:
        # 1-2. What to search for
        search = await self.search_planner.plan(request)
        search, warnings = enforce_request_filters(search, request)

        # 3. Fetch every group in parallel
        results = await asyncio.gather(
            *(self.source.search(search_params_for(search, g), self.max_trials_per_group) for g in search.groups)
        )
        trials_by_group = {g.label: r.trials for g, r in zip(search.groups, results)}
        total_matched = sum(r.total_matched for r in results)
        trials_fetched = sum(len(t) for t in trials_by_group.values())
        if trials_fetched == 0:
            raise NoResults("No trials matched the search.", {"filters": filters_summary(search)})
        for group, result in zip(search.groups, results):
            if result.truncated:
                warnings.append(
                    f"{group.label}: analyzed {len(result.trials)} of {result.total_matched} matching trials."
                )
            if not result.trials and search.is_comparison:
                warnings.append(f"{group.label}: no matching trials.")

        # 4-6. How to show it
        profile = self.profiler.profile(trials_by_group, total_matched)
        chart = await self.chart_planner.plan(request, search, profile)
        warnings += check_chart_plan(chart, search, profile)

        # 7-8. Build and assemble
        visualization = self.visualizer.build(trials_by_group, chart)
        meta = Meta(
            interpretation=search.interpretation,
            filters_applied=filters_summary(search),
            warnings=warnings,
            total_trials_matched=total_matched,
            trials_analyzed=trials_fetched,
            units={"trial_count": "trials"},
        )
        return QueryResponse(visualization=visualization, meta=meta)


def check_chart_plan(chart: ChartPlan, search: SearchPlan, profile: DataProfile) -> list[str]:
    """Reject plans the data cannot support; return warnings for weak ones."""
    used = [d for d in (chart.x, chart.series) if d is not None]
    if Dimension.GROUP in used and not search.is_comparison:
        raise UnsupportedQuery("The chart groups by comparison side, but the search has only one group.")

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
