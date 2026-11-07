"""The query workflow: request in, one visualization out.

    1. Query agent (one LLM run)  plans API calls with the ctgov-search skill and calls
                                  fetch_data -> code runs step 2 and 3 -> describe_data
                                  -> loads the chart-planning skill -> ChartPlan
    2. Add user filters (code)    structured fields AND-ed onto every /studies step
    3. Fetch (code)               every step in parallel, every page, one data version
    4. Check the chart plan       against the fetched data, before the agent's answer is accepted
    5. Visualize (code)           trials + ChartPlan -> visualization with citations
    6. Assemble                   visualization + meta -> QueryResponse
"""

import asyncio
import logging
from dataclasses import dataclass

from cheiron.fetch.endpoints import StudyStep
from cheiron.fetch.models import SNAPSHOT_API_VERSION, DataVersion, StudySearchParams, Trial
from cheiron.models.request import QueryRequest
from cheiron.models.response import Meta, QueryResponse
from cheiron.workflow.errors import InvalidSearch, NoResults, UnsupportedQuery, UpstreamError
from cheiron.workflow.plans import (
    ChartPlan,
    DataProfile,
    Dimension,
    FetchResult,
    Progress,
    ProgressCallback,
    SearchPlan,
    StatsResult,
    StepResult,
)
from cheiron.workflow.steps import QueryPlanner, TrialSource
from cheiron.workflow.translate import PreparedStep, apply_request_filters, filters_summary

log = logging.getLogger(__name__)

MISSING_WARNING_SHARE = 0.10  # warn when more than 10% of trials lack the plotted value
FETCH_ATTEMPTS = 2  # first fetch + one redo if the data was refreshed mid-fetch


@dataclass
class FetchOutcome:
    """Everything one fetch_data call produced: every step executed, on one data version."""

    plan: SearchPlan  # as the agent wrote it
    prepared: list[PreparedStep]  # as executed, after the user's filters were added
    results: list[StepResult]  # one per prepared step, same order
    version: DataVersion
    warnings: list[str]

    @property
    def trials_by_group(self) -> dict[str, list[Trial]]:
        return {label: r.trials for (label, _), r in zip(self.prepared, self.results) if isinstance(r, FetchResult)}

    @property
    def total_matched(self) -> int:
        return sum(r.total_matched for r in self.results if isinstance(r, FetchResult))

    @property
    def trials_fetched(self) -> int:
        return sum(len(r.trials) for r in self.results if isinstance(r, FetchResult))

    @property
    def stats_fetched(self) -> int:
        return sum(isinstance(r, StatsResult) for r in self.results)


def _report(progress: ProgressCallback | None, stage: str, message: str, **numbers) -> None:
    if progress:
        progress(Progress(stage=stage, message=message, **numbers))


@dataclass
class QueryWorkflow:
    agent: QueryPlanner
    source: TrialSource
    # None = fetch every matching trial. Counts must be exact; long fetches run as
    # async tasks with status updates, so correctness wins over latency.
    max_trials_per_search: int | None = None

    async def run(
        self, request: QueryRequest, progress: ProgressCallback | None = None
    ) -> tuple[QueryResponse, FetchOutcome]:
        """Answer one question: the agent plans, fetches and chooses; code builds the response."""
        from cheiron.visualize.builder import build_visualization  # visualize depends on workflow

        _report(progress, "planning", "Planning API calls")

        async def fetch(plan: SearchPlan) -> FetchOutcome:
            return await self.fetch_plan(plan, request, progress)

        result = await self.agent.decide(request, fetch)
        outcome, chart = result.outcome, result.chart

        _report(progress, "building", "Building the chart")
        visualization, viz_warnings = build_visualization(outcome.trials_by_group, chart)
        meta = Meta(
            interpretation=outcome.plan.rationale,
            filters_applied=filters_summary(outcome.prepared),
            assumptions=_assumptions(chart, result.profile),
            warnings=outcome.warnings + result.chart_warnings + viz_warnings,
            total_trials_matched=outcome.total_matched,
            trials_analyzed=outcome.trials_fetched,
            units={"trial_count": "trials"},
            data_as_of=outcome.version.data_timestamp,
            api_version=outcome.version.api_version,
        )
        return QueryResponse(visualization=visualization, meta=meta), outcome

    async def fetch_plan(
        self, search: SearchPlan, request: QueryRequest, progress: ProgressCallback | None = None
    ) -> FetchOutcome:
        """Execute a plan: add the user's filters, fetch every step on one data version.

        Raises InvalidSearch (the API or a rule rejected the plan) or NoResults (nothing matched);
        both carry a message meant for the agent to fix its plan.
        """
        try:
            prepared, warnings = apply_request_filters(search, request)
            results, version = await self._fetch_consistent(prepared, progress)
        except InvalidSearch as exc:
            raise InvalidSearch(f"The plan was rejected: {exc.message}", exc.details) from exc
        if not any(isinstance(r, StatsResult) or r.total_matched for r in results):
            summary = filters_summary(prepared)
            raise NoResults(f"No trials matched these steps: {summary['steps']}", summary)
        for (label, _), result in zip(prepared, results):
            if isinstance(result, StatsResult):
                if result.incomplete_fields:
                    warnings.append(
                        f"{label}: the API returns only the top values for {result.incomplete_fields}; "
                        "registry-wide counts for the rest are not available."
                    )
                continue
            if result.truncated:
                warnings.append(f"{label}: analyzed {len(result.trials)} of {result.total_matched} matching trials.")
            if not result.trials and search.is_comparison:
                warnings.append(f"{label}: no matching trials.")
        return FetchOutcome(search, prepared, results, version, warnings)

    def _execute(self, index: int, target, tracker: "_FetchTracker"):
        """The client call for one prepared step."""
        if isinstance(target, StudySearchParams):
            return self.source.search(target, self.max_trials_per_search, tracker.callback(index))
        if isinstance(target, StudyStep):
            return self.source.fetch_study(target)
        return self.source.fetch_stats(target)

    async def _fetch_consistent(
        self, prepared: list[PreparedStep], progress: ProgressCallback | None
    ) -> tuple[list[StepResult], DataVersion]:
        """Run every search against one version of the data.

        The registry refreshes daily; a fetch that spans a refresh could mix two
        versions (trials double-counted or missed across pages, comparison sides on
        different data). So the data timestamp is read before and after, and the
        fetch is redone once if it changed.
        """
        for _ in range(FETCH_ATTEMPTS):
            before = await self.source.data_version()
            warn_if_docs_outdated(before)
            searches = [i for i, (_, target) in enumerate(prepared) if isinstance(target, StudySearchParams)]
            tracker = _FetchTracker(searches, progress)
            results = await asyncio.gather(*(self._execute(i, target, tracker) for i, (_, target) in enumerate(prepared)))
            after = await self.source.data_version()
            if after.data_timestamp == before.data_timestamp:
                return list(results), after
            log.warning("data refreshed during fetch (%s -> %s); fetching again", before.data_timestamp, after.data_timestamp)
        raise UpstreamError("ClinicalTrials.gov data changed during every fetch attempt; try again shortly.")


class _FetchTracker:
    """Sums page progress across parallel /studies searches into one status message."""

    def __init__(self, search_indexes: list[int], progress: ProgressCallback | None):
        self.fetched: dict[int, int] = {i: 0 for i in search_indexes}
        self.totals: dict[int, int | None] = {i: None for i in search_indexes}
        self.progress = progress

    def callback(self, index: int):
        def on_page(fetched: int, total: int | None) -> None:
            self.fetched[index], self.totals[index] = fetched, total
            done = sum(self.fetched.values())
            totals = list(self.totals.values())
            total_all = sum(t for t in totals if t is not None) if None not in totals else None
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
        if field.multi_valued and chart.chart_type == "stacked_bar_chart":
            raise UnsupportedQuery(
                f"{dim.value} can have several values per trial, so stacked parts would not add up to the whole; "
                "use a grouped bar chart instead."
            )
        if field.missing > MISSING_WARNING_SHARE * profile.trials_fetched:
            warnings.append(f"{field.missing} of {profile.trials_fetched} trials have no {dim.value} and are excluded.")
    return warnings


def _assumptions(chart: ChartPlan, profile: DataProfile) -> list[str]:
    """Counting rules the reader needs to read the chart correctly."""
    notes = ["Counts are distinct trials."]
    multi = [d.value for d in (chart.x, chart.series) if d and d in profile.fields and profile.fields[d].multi_valued]
    if multi:
        notes.append(f"A trial can have several values of {', '.join(sorted(set(multi)))}, so counts can sum to more than the trials.")
    if len(profile.group_sizes) > 1:
        notes.append("Compared sides are separate searches; a trial matching several sides is counted in each.")
    return notes
