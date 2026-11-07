"""The query workflow: request in, one visualization out.

    1. Search planner (agent)   request (all fields) -> SearchPlan (API searches it wrote)
    2. Add user filters (code)  structured fields AND-ed onto every search
    3. Fetch (code)             one search per side, in parallel, all pages
       -> API error or no results: feedback to the planner, one retry
       -> data refreshed mid-fetch: fetch again, so all results share one data version
    4. Profile (code)           trials              -> DataProfile
    5. Chart planner (agent)    request + profile   -> ChartPlan
    6. Check the chart plan     against what was fetched
    7. Visualize (code)         trials + ChartPlan  -> visualization with citations
    8. Assemble                 visualization + meta -> QueryResponse

Steps 1-3 are `plan_and_fetch()`; `run()` does all eight. The chart steps (4-7) are
optional until they are built: a workflow without them can still plan and fetch.
"""

import asyncio
import logging
from dataclasses import dataclass

from cheiron.fetch.models import SNAPSHOT_API_VERSION, DataVersion, Trial
from cheiron.models.request import QueryRequest
from cheiron.models.response import Meta, QueryResponse
from cheiron.workflow.errors import InvalidSearch, NoResults, UnsupportedQuery, UpstreamError
from cheiron.workflow.plans import ChartPlan, DataProfile, Dimension, FetchResult, Progress, ProgressCallback, SearchPlan
from cheiron.workflow.steps import ChartPlanner, Profiler, SearchPlanner, TrialSource, Visualizer
from cheiron.workflow.translate import PreparedSearch, apply_request_filters, filters_summary

log = logging.getLogger(__name__)

MISSING_WARNING_SHARE = 0.10  # warn when more than 10% of trials lack the plotted value
PLANNING_ATTEMPTS = 2  # first plan + one retry with feedback
FETCH_ATTEMPTS = 2  # first fetch + one redo if the data was refreshed mid-fetch


@dataclass
class FetchOutcome:
    """Result of steps 1-3: what was searched and every trial found, on one data version."""

    plan: SearchPlan  # as the planner wrote it
    prepared: list[PreparedSearch]  # as executed, after the user's filters were added
    results: list[FetchResult]  # one per prepared search, same order
    version: DataVersion
    warnings: list[str]

    @property
    def trials_by_group(self) -> dict[str, list[Trial]]:
        return {label: r.trials for (label, _), r in zip(self.prepared, self.results)}

    @property
    def total_matched(self) -> int:
        return sum(r.total_matched for r in self.results)

    @property
    def trials_fetched(self) -> int:
        return sum(len(r.trials) for r in self.results)


def _report(progress: ProgressCallback | None, stage: str, message: str, **numbers) -> None:
    if progress:
        progress(Progress(stage=stage, message=message, **numbers))


@dataclass
class QueryWorkflow:
    search_planner: SearchPlanner
    source: TrialSource
    profiler: Profiler | None = None
    chart_planner: ChartPlanner | None = None
    visualizer: Visualizer | None = None
    # None = fetch every matching trial. Counts must be exact; long fetches run as
    # async tasks with status updates, so correctness wins over latency.
    max_trials_per_search: int | None = None

    async def run(self, request: QueryRequest, progress: ProgressCallback | None = None) -> QueryResponse:
        if not (self.profiler and self.chart_planner and self.visualizer):
            raise RuntimeError("run() needs the profiler, chart planner and visualizer; use plan_and_fetch().")
        fetched = await self.plan_and_fetch(request, progress)
        warnings = list(fetched.warnings)

        # 4-6. How to show it
        _report(progress, "analyzing", "Choosing the chart")
        profile = self.profiler.profile(fetched.trials_by_group, fetched.total_matched)
        chart = await self.chart_planner.plan(request, fetched.plan, profile)
        warnings += check_chart_plan(chart, fetched.plan, profile)

        # 7-8. Build and assemble
        _report(progress, "building", "Building the chart")
        visualization = self.visualizer.build(fetched.trials_by_group, chart)
        meta = Meta(
            interpretation=fetched.plan.rationale,
            filters_applied=filters_summary(fetched.prepared),
            warnings=warnings,
            total_trials_matched=fetched.total_matched,
            trials_analyzed=fetched.trials_fetched,
            units={"trial_count": "trials"},
            data_as_of=fetched.version.data_timestamp,
            api_version=fetched.version.api_version,
        )
        return QueryResponse(visualization=visualization, meta=meta)

    async def plan_and_fetch(self, request: QueryRequest, progress: ProgressCallback | None = None) -> FetchOutcome:
        """Steps 1-3: plan the searches, add the user's filters, fetch every matching trial."""
        feedback: list[str] | None = None
        for attempt in range(1, PLANNING_ATTEMPTS + 1):
            _report(progress, "planning", "Planning searches" if feedback is None else "Revising searches after feedback")
            search = await self.search_planner.plan(request, feedback)
            prepared, warnings = apply_request_filters(search, request)
            try:
                results, version = await self._fetch_consistent(prepared, progress)
            except InvalidSearch as exc:
                if attempt == PLANNING_ATTEMPTS:
                    raise
                feedback = [f"The API rejected a search: {exc.message}"]
                continue
            if any(r.total_matched for r in results):
                for (label, _), result in zip(prepared, results):
                    if result.truncated:
                        warnings.append(f"{label}: analyzed {len(result.trials)} of {result.total_matched} matching trials.")
                    if not result.trials and search.is_comparison:
                        warnings.append(f"{label}: no matching trials.")
                return FetchOutcome(search, prepared, results, version, warnings)
            if attempt == PLANNING_ATTEMPTS:
                raise NoResults("No trials matched the search.", filters_summary(prepared))
            feedback = [f"No trials matched these searches: {filters_summary(prepared)['searches']}"]
        raise AssertionError("unreachable")

    async def _fetch_consistent(
        self, prepared: list[PreparedSearch], progress: ProgressCallback | None
    ) -> tuple[list[FetchResult], DataVersion]:
        """Run every search against one version of the data.

        The registry refreshes daily; a fetch that spans a refresh could mix two
        versions (trials double-counted or missed across pages, comparison sides on
        different data). So the data timestamp is read before and after, and the
        fetch is redone once if it changed.
        """
        for _ in range(FETCH_ATTEMPTS):
            before = await self.source.data_version()
            warn_if_docs_outdated(before)
            tracker = _FetchTracker(len(prepared), progress)
            results = await asyncio.gather(
                *(
                    self.source.search(params, self.max_trials_per_search, tracker.callback(i))
                    for i, (_, params) in enumerate(prepared)
                )
            )
            after = await self.source.data_version()
            if after.data_timestamp == before.data_timestamp:
                return list(results), after
            log.warning("data refreshed during fetch (%s -> %s); fetching again", before.data_timestamp, after.data_timestamp)
        raise UpstreamError("ClinicalTrials.gov data changed during every fetch attempt; try again shortly.")


class _FetchTracker:
    """Sums page progress across parallel searches into one status message."""

    def __init__(self, searches: int, progress: ProgressCallback | None):
        self.fetched = [0] * searches
        self.totals: list[int | None] = [None] * searches
        self.progress = progress

    def callback(self, index: int):
        def on_page(fetched: int, total: int | None) -> None:
            self.fetched[index], self.totals[index] = fetched, total
            done = sum(self.fetched)
            total_all = sum(t for t in self.totals if t is not None) if None not in self.totals else None
            message = f"Fetching trials: {done:,} of {total_all:,}" if total_all is not None else f"Fetching trials: {done:,}"
            _report(self.progress, "fetching", message, trials_fetched=done, trials_total=total_all)

        return on_page


def warn_if_docs_outdated(version: DataVersion) -> None:
    """Log once if the live API version differs from the one our docs and skill describe."""
    global _docs_warning_logged
    if version.api_version != SNAPSHOT_API_VERSION and not _docs_warning_logged:
        _docs_warning_logged = True
        log.warning(
            "ClinicalTrials.gov API is %s but docs/ctgov and the ctgov-search skill describe %s. "
            "Run scripts/refresh_ctgov_docs.py and scripts/build_ctgov_skill.py, then review the diff.",
            version.api_version,
            SNAPSHOT_API_VERSION,
        )


_docs_warning_logged = False


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
