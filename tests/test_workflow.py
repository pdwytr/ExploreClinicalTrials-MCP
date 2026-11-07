"""The workflow's wiring, with every step replaced by a small fake."""

import asyncio
from collections import Counter

import pytest

from cheiron.fetch.models import Trial
from cheiron.models.request import QueryRequest
from cheiron.models.response import ChartVisualization
from cheiron.workflow import (
    ChartPlan,
    DataProfile,
    Dimension,
    FetchResult,
    FieldProfile,
    InvalidSearch,
    NoResults,
    QueryWorkflow,
    SearchPlan,
    UnsupportedQuery,
)

# --- Fakes ---------------------------------------------------------------------------


def trial(n: int, phase: str = "PHASE2", year: int | None = 2020) -> Trial:
    return Trial(nct_id=f"NCT{n:08d}", phases=[phase], start_date=f"{year}-01-01" if year else None)


def search_plan(*interventions: str) -> SearchPlan:
    return SearchPlan(
        searches=[{"label": i.title(), "params": {"query.intr": i}} for i in interventions],
        rationale=f"Trials of {' vs '.join(interventions)}",
    )


class FakeSearchPlanner:
    """Returns the given plans in order (the second one answers feedback); records feedback."""

    def __init__(self, *plans: SearchPlan):
        self.plans = list(plans)
        self.feedback_seen = []

    async def plan(self, request, feedback=None):
        self.feedback_seen.append(feedback)
        return self.plans.pop(0)


class FakeSource:
    """Returns canned results keyed by the query.intr searched; records every call."""

    def __init__(self, by_intervention: dict[str, FetchResult | Exception]):
        self.by_intervention = by_intervention
        self.calls = []

    async def search(self, params, limit):
        self.calls.append(params)
        result = self.by_intervention.get(params.search.get("query.intr"), FetchResult(trials=[], total_matched=0))
        if isinstance(result, Exception):
            raise result
        return result


class FakeProfiler:
    def profile(self, trials_by_group, total_matched):
        trials = [t for ts in trials_by_group.values() for t in ts]
        return DataProfile(
            total_matched=total_matched,
            trials_fetched=len(trials),
            group_sizes={g: len(ts) for g, ts in trials_by_group.items()},
            fields={
                Dimension.PHASE: FieldProfile(distinct=1, missing=0),
                Dimension.START_YEAR: FieldProfile(distinct=1, missing=sum(t.start_date is None for t in trials)),
            },
        )


class FakeChartPlanner:
    def __init__(self, plan: ChartPlan):
        self.result = plan
        self.seen_profile = None

    async def plan(self, request, search, profile):
        self.seen_profile = profile
        return self.result


class FakeVisualizer:
    """Counts trials per phase (enough for wiring tests)."""

    def build(self, trials_by_group, plan):
        counts = Counter(p for ts in trials_by_group.values() for t in ts for p in t.phases)
        return ChartVisualization(
            type=plan.chart_type,
            intent=plan.intent,
            title=plan.title,
            encoding={"x": {"field": "phase", "type": "ordinal"}, "y": {"field": "trial_count", "type": "quantitative"}},
            data=[{"phase": k, "trial_count": v} for k, v in counts.items()],
        )


BY_PHASE = ChartPlan(intent="distribution", chart_type="bar_chart", title="Trials by phase", x=Dimension.PHASE)
FOUND = FetchResult(trials=[trial(1), trial(2, "PHASE3")], total_matched=2)


def make_workflow(plans, fetched, chart_plan=BY_PHASE):
    planner = FakeSearchPlanner(*plans)
    source = FakeSource(fetched)
    chart_planner = FakeChartPlanner(chart_plan)
    wf = QueryWorkflow(planner, source, FakeProfiler(), chart_planner, FakeVisualizer())
    return wf, planner, source, chart_planner


def run(wf, **request):
    return asyncio.run(wf.run(QueryRequest(query="test question", **request)))


# --- Happy path ------------------------------------------------------------------------


def test_single_search_runs_end_to_end():
    wf, planner, source, chart_planner = make_workflow([search_plan("pembrolizumab")], {"pembrolizumab": FOUND})

    resp = run(wf)

    assert planner.feedback_seen == [None]  # planned once, no retry
    assert len(source.calls) == 1
    assert chart_planner.seen_profile.trials_fetched == 2  # agent 2 saw the data profile
    assert resp.meta.interpretation == "Trials of pembrolizumab"
    assert resp.meta.filters_applied == {"searches": [{"label": "Pembrolizumab", "params": {"query.intr": "pembrolizumab"}}]}
    assert resp.meta.total_trials_matched == 2
    assert resp.vega_lite is not None


def test_comparison_runs_one_search_per_side():
    fetched = {"nivolumab": FetchResult(trials=[trial(1)], total_matched=1), "pembrolizumab": FOUND}
    wf, _, source, chart_planner = make_workflow([search_plan("nivolumab", "pembrolizumab")], fetched)

    run(wf)

    assert sorted(p.search["query.intr"] for p in source.calls) == ["nivolumab", "pembrolizumab"]
    assert chart_planner.seen_profile.group_sizes == {"Nivolumab": 1, "Pembrolizumab": 2}


def test_user_filters_reach_the_api():
    wf, _, source, _ = make_workflow([search_plan("pembrolizumab")], {"pembrolizumab": FOUND})

    run(wf, trial_phase=["PHASE3"])

    assert source.calls[0].search["filter.advanced"] == "AREA[Phase](PHASE3)"


# --- Feedback and retry ------------------------------------------------------------------


def test_no_results_triggers_one_retry_with_feedback():
    wf, planner, _, _ = make_workflow(
        [search_plan("pembrolizmab"), search_plan("pembrolizumab")],  # typo first, fixed on retry
        {"pembrolizumab": FOUND},
    )

    resp = run(wf)

    assert planner.feedback_seen[0] is None
    assert "No trials matched" in planner.feedback_seen[1][0]
    assert resp.meta.trials_analyzed == 2


def test_api_rejection_triggers_one_retry_with_feedback():
    wf, planner, _, _ = make_workflow(
        [search_plan("bad syntax"), search_plan("pembrolizumab")],
        {"bad syntax": InvalidSearch("unbalanced parenthesis"), "pembrolizumab": FOUND},
    )

    run(wf)

    assert "unbalanced parenthesis" in planner.feedback_seen[1][0]


def test_still_no_results_after_retry_raises_no_results():
    wf, _, _, _ = make_workflow([search_plan("x"), search_plan("y")], {})
    with pytest.raises(NoResults) as exc:
        run(wf)
    assert exc.value.to_response().error == "no_results"


def test_still_rejected_after_retry_raises():
    bad = InvalidSearch("bad")
    wf, _, _, _ = make_workflow([search_plan("x"), search_plan("y")], {"x": bad, "y": bad})
    with pytest.raises(InvalidSearch):
        run(wf)


# --- Warnings and chart checks -------------------------------------------------------------


def test_truncated_fetch_is_reported():
    big = FetchResult(trials=[trial(1)], total_matched=900)
    wf, _, _, _ = make_workflow([search_plan("pembrolizumab")], {"pembrolizumab": big})

    resp = run(wf)

    assert any("analyzed 1 of 900" in w for w in resp.meta.warnings)


def test_grouping_by_side_without_a_comparison_is_rejected():
    by_group = ChartPlan(
        intent="magnitude", chart_type="grouped_bar_chart", title="t", x=Dimension.PHASE, series=Dimension.GROUP
    )
    wf, _, _, _ = make_workflow([search_plan("pembrolizumab")], {"pembrolizumab": FOUND}, by_group)
    with pytest.raises(UnsupportedQuery):
        run(wf)


def test_mostly_missing_dimension_is_warned():
    by_year = ChartPlan(intent="change_over_time", chart_type="time_series", title="t", x=Dimension.START_YEAR)
    fetched = {"pembrolizumab": FetchResult(trials=[trial(1), trial(2, year=None)], total_matched=2)}
    wf, _, _, _ = make_workflow([search_plan("pembrolizumab")], fetched, by_year)

    resp = run(wf)

    assert any("have no start_year" in w for w in resp.meta.warnings)


def test_chart_plan_must_fit_catalog():
    with pytest.raises(ValueError, match="does not fit"):
        ChartPlan(intent="ranking", chart_type="scatter_plot", title="t", x=Dimension.ENROLLMENT)
    with pytest.raises(ValueError, match="needs a series"):
        ChartPlan(intent="relationship", chart_type="network_graph", title="t", x=Dimension.SPONSOR)
