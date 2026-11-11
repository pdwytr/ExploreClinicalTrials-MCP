"""The query workflow: request in, one visualization out.

    1. Query agent (LLM)          plans API calls (specs/query-agent.yaml) and calls
                                  fetch_data -> code runs step 2 and 3 -> describe_data
                                  -> plan_chart: the chart planner sub-agent -> ChartPlan
    2. Add user filters (code)    structured fields AND-ed onto every /studies step
    3. Fetch (code)               every step in parallel, every page, one data version
    4. Check the chart plan       against the fetched data, before the agent's answer is accepted
    5. Visualize (code)           trials + ChartPlan -> visualization with citations
    6. Assemble                   visualization + meta -> QueryResponse
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field

from exploreclinicaltrials.fetch.endpoints import StudyStep
from exploreclinicaltrials.fetch.models import SNAPSHOT_API_VERSION, DataVersion, StudySearchParams, Trial
from exploreclinicaltrials.models.request import QueryRequest
from exploreclinicaltrials.models.response import ChainStep, Meta, QueryResponse
from exploreclinicaltrials.workflow.errors import InvalidSearch, NoResults, UnsupportedQuery, UpstreamError
from exploreclinicaltrials.workflow.plans import (
    ChartPlan,
    DataProfile,
    Dimension,
    FetchResult,
    Progress,
    ProgressCallback,
    SearchPlan,
    StatsResult,
    StepResult,
    YEAR_DIMENSIONS,
)
from exploreclinicaltrials.workflow.steps import AgentResult, FetchRecord, QueryPlanner, RunLog, TrialSource
from exploreclinicaltrials.workflow.trace import run_metrics
from exploreclinicaltrials.workflow.intent import Resolver, contains_term
from exploreclinicaltrials.workflow.translate import PreparedStep, filters_summary, prepare_plan, year_bounds

log = logging.getLogger(__name__)

MISSING_WARNING_SHARE = 0.10  # warn when more than 10% of trials lack the plotted value
SMALL_SAMPLE = 10  # warn when fewer trials than this back the chart
FETCH_ATTEMPTS = 2  # first fetch + one redo if the data was refreshed mid-fetch


@dataclass
class FetchOutcome:
    """Everything one fetch_data call produced: every step executed, on one data version."""

    plan: SearchPlan  # as the agent wrote it
    prepared: list[PreparedStep]  # as executed, after the user's filters were added
    results: list[StepResult]  # one per prepared step, same order
    version: DataVersion
    warnings: list[str]
    notes: list[str] = field(default_factory=list)  # resolutions and replaced terms, for meta.assumptions
    descriptions: list[str] = field(default_factory=list)  # what each search covers, in plain words

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
    resolver: Resolver | None = None  # how names map to the registry's own; built from `source` if not given

    def __post_init__(self) -> None:
        if self.resolver is None:
            self.resolver = Resolver(self.source.search, getattr(self.source, "fetch_stats", None))

    async def run(
        self, request: QueryRequest, progress: ProgressCallback | None = None, log: RunLog | None = None
    ) -> tuple[QueryResponse, AgentResult]:
        """Answer one question: the agent plans, fetches and chooses; code builds the response.

        `log` records what the agent did (fetches, messages, time); pass one in to keep it
        when the run fails."""
        log = log if log is not None else RunLog()
        from exploreclinicaltrials.visualize.builder import build_visualization  # visualize depends on workflow

        _report(progress, "planning", "Planning API calls")

        async def fetch(plan: SearchPlan) -> FetchOutcome:
            return await self.fetch_plan(plan, request, progress)

        result = await self.agent.decide(request, fetch, log)
        outcome, chart = result.outcome, result.chart

        _report(progress, "building", "Building the chart")
        build_started = time.perf_counter()
        bounds = year_bounds(outcome.plan, request)
        stats = [(label, r) for (label, _), r in zip(outcome.prepared, outcome.results) if isinstance(r, StatsResult)]
        visualization, viz_warnings = build_visualization(
            outcome.trials_by_group, chart, bounds, outcome.version.data_timestamp.date(), stats
        )
        meta = Meta(
            interpretation=_interpretation(result, log.fetches),
            request_filters=request.filters(),
            filters_applied=filters_summary(outcome.prepared),
            assumptions=outcome.notes + _assumptions(chart, result.profile),
            warnings=outcome.warnings + result.chart_warnings + viz_warnings,
            total_trials_matched=outcome.total_matched,
            trials_analyzed=outcome.trials_fetched,
            units=_units(visualization),
            data_as_of=outcome.version.data_timestamp,
            api_version=outcome.version.api_version,
            chain=_chain(result, log.fetches),
        )
        meta.metrics = run_metrics(log.all_messages, log.fetches, log.seconds, time.perf_counter() - build_started)
        return QueryResponse(visualization=visualization, meta=meta), result

    async def fetch_plan(
        self, search: SearchPlan, request: QueryRequest, progress: ProgressCallback | None = None
    ) -> FetchOutcome:
        """Execute a plan: add the user's filters, fetch every step on one data version.

        Raises InvalidSearch (the API or a rule rejected the plan) or NoResults (nothing matched);
        both carry a message meant for the agent to fix its plan.
        """
        try:
            plan = await prepare_plan(search, request, self.resolver)
            prepared, warnings = plan.steps, plan.warnings
            results, version = await self._fetch_consistent(prepared, progress)
        except InvalidSearch as exc:
            raise InvalidSearch(f"The plan was rejected: {exc.message}", exc.details) from exc
        results = [_within_countries(target, r) for (_, target), r in zip(prepared, results)]
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
        return FetchOutcome(search, prepared, results, version, warnings, plan.notes, plan.descriptions)

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
    """Log once if the live API version differs from the one the agent specs and evals were checked on."""
    global _docs_warning_logged
    if version.api_version != SNAPSHOT_API_VERSION and not _docs_warning_logged:
        _docs_warning_logged = True
        log.warning(
            "ClinicalTrials.gov API is %s but the agent specs and evals were last checked on %s. "
            "The agent reads the live API reference; rerun the evals, then scripts/refresh_ctgov_docs.py.",
            version.api_version,
            SNAPSHOT_API_VERSION,
        )


_docs_warning_logged = False


def check_chart_plan(
    chart: ChartPlan, search: SearchPlan, profile: DataProfile, bounds: dict | None = None
) -> list[str]:
    """Reject plans the data cannot support; return warnings for weak ones.
    `bounds` are the year ranges the searches were filtered on, per date field."""
    used = [d for d in (chart.x, chart.series, chart.y) if d is not None]
    if Dimension.GROUP in used and not search.is_comparison:
        raise UnsupportedQuery("The chart groups by comparison side, but there is only one search.")
    for dim in used:
        field = YEAR_DIMENSIONS.get(dim)
        if field and bounds and field not in bounds:
            raise UnsupportedQuery(
                f"The chart counts by {dim.value} but the searches are limited by {', '.join(bounds)} date; "
                f"use the year field that matches the period ({', '.join(f'{f}_year' for f in bounds)})."
            )

    if any(f.from_registry_stats for f in profile.fields.values()):
        if chart.chart_type != "bar_chart" or chart.series is not None:
            raise UnsupportedQuery("Registry-wide statistics give counts for one field: use a bar_chart with x only.")
        if chart.measure == "share":
            raise UnsupportedQuery("Registry-wide statistics give counts only; a share needs a studies search.")
        if chart.x not in profile.fields:
            raise UnsupportedQuery(f"No registry statistics were fetched for {chart.x.value}; add it to the stats step's fields.")
        return []

    warnings = []
    if chart.chart_type == "time_series":
        years = profile.fields.get(chart.x)
        if years is None or years.distinct < 2:
            raise UnsupportedQuery(
                f"Only {years.distinct if years else 0} year has data, so a time series shows no change; "
                "use a bar chart instead."
            )
    if profile.trials_fetched < SMALL_SAMPLE:
        warnings.append(f"Only {profile.trials_fetched} trials match; rankings and trends rest on very few trials.")
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
        if field.missing > MISSING_WARNING_SHARE * profile.trials_fetched and chart.chart_type != "scatter_plot":  # scatter says it
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
    if chart.measure == "share":
        of = (
            f"all charted trials with values for both {chart.x.value.replace('_', ' ')} and {chart.series.value.replace('_', ' ')}"
            if chart.share_of == "all"
            else "each compared side" if chart.series is Dimension.GROUP
            else f"the trials in each {chart.x.value.replace('_', ' ')}" if chart.series
            else f"all charted trials with a {chart.x.value.replace('_', ' ')}"
        )  # fmt: skip
        notes.append(f"Percentages are shares of {of} (of_trials on each row).")
    return notes


def _chain(result: AgentResult, fetches: list[FetchRecord]) -> list[ChainStep]:
    """Every fetch the agent made, in order, so a reader can check intermediate findings."""
    chain = []
    for record in fetches:
        ok = record.outcome is not None
        chain.append(
            ChainStep(
                fetch=record.number,
                rationale=record.plan.rationale,
                searches=filters_summary(record.outcome.prepared)["steps"] if ok else record.plan.model_dump(mode="json")["steps"],
                status="ok" if ok else "failed",
                total_trials_matched=record.outcome.total_matched if ok else None,
                error=record.error,
                charted=record.outcome is result.outcome,
                output_dir=f"fetch-{record.number}",
            )
        )
    return chain


def _units(visualization) -> dict[str, str]:
    """What each number in the data counts, by the key it appears under."""
    if visualization.type == "network_graph":
        return {"size": "trials with this value", "weight": "trials that have both values"}
    if visualization.type == "scatter_plot":  # one point per trial
        known = {"enrollment": "participants", "duration_months": "months from start to actual primary completion"}
        enc = visualization.encoding
        return {f: known[f] for f in (enc.x.field, enc.y.field) if f in known}
    units = {"trial_count": "trials"}
    if visualization.encoding.y.field == "percent":
        units |= {"percent": "percent of the trials in of_trials", "of_trials": "trials (the share's denominator)"}
    if visualization.type == "histogram":
        units |= {"enrollment_from": "participants", "enrollment_to": "participants (exclusive; null = no upper bound)"}
    return units


def _within_countries(target, result: StepResult) -> StepResult:
    """A search limited to some countries charts only those: a trial's other site countries are
    dropped from its record (a 'European countries' question must not chart the US)."""
    if not isinstance(target, StudySearchParams) or not target.countries or not isinstance(result, FetchResult):
        return result
    keep = lambda country: any(contains_term(country, c) or contains_term(c, country) for c in target.countries)  # noqa: E731
    trials = [t.model_copy(update={"countries": [c for c in t.countries if keep(c)]}) for t in result.trials]
    return result.model_copy(update={"trials": trials})


def _interpretation(result: AgentResult, fetches: list[FetchRecord]) -> str:
    """What was searched, written by code from the compiled steps (never the model's own prose,
    which stays in meta.chain as the rationale). Earlier fetches of a multi-step run come first."""
    charted = " ".join(result.outcome.descriptions) or result.outcome.plan.rationale
    earlier = [r.outcome for r in fetches if r.outcome is not None and r.outcome is not result.outcome]
    if not earlier:
        return charted
    found = " ".join(f"Fetch {i}: {' '.join(o.descriptions)}" for i, o in enumerate(earlier, start=1))
    return f"{found} Charted: {charted}"
