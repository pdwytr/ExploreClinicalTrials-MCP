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
    NoResults,
    QueryWorkflow,
    SearchGroup,
    SearchPlan,
    UnsupportedQuery,
)
from cheiron.workflow.translate import phrase

# --- Fakes ---------------------------------------------------------------------------


def trial(n: int, phase: str = "PHASE2", year: int | None = 2020) -> Trial:
    return Trial(nct_id=f"NCT{n:08d}", phases=[phase], start_date=f"{year}-01-01" if year else None)


class FakeSearchPlanner:
    def __init__(self, plan: SearchPlan):
        self.result = plan

    async def plan(self, request):
        return self.result


class FakeSource:
    """Returns canned results keyed by the intervention searched; records every call."""

    def __init__(self, by_intervention: dict[str, FetchResult]):
        self.by_intervention = by_intervention
        self.calls = []

    async def search(self, params, limit):
        self.calls.append(params)
        return self.by_intervention.get(params.intervention, FetchResult(trials=[], total_matched=0))


class FakeProfiler:
    def profile(self, trials_by_group, total_matched):
        trials = [t for ts in trials_by_group.values() for t in ts]
        missing_year = sum(t.start_date is None for t in trials)
        return DataProfile(
            total_matched=total_matched,
            trials_fetched=len(trials),
            group_sizes={g: len(ts) for g, ts in trials_by_group.items()},
            fields={
                Dimension.PHASE: FieldProfile(distinct=1, missing=0),
                Dimension.START_YEAR: FieldProfile(distinct=1, missing=missing_year),
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
    """Counts trials per value of the x dimension (phase only, enough for wiring tests)."""

    def build(self, trials_by_group, plan):
        counts = Counter(p for ts in trials_by_group.values() for t in ts for p in t.phases)
        return ChartVisualization(
            type=plan.chart_type,
            intent=plan.intent,
            title=plan.title,
            encoding={"x": {"field": "phase", "type": "ordinal"}, "y": {"field": "trial_count", "type": "quantitative"}},
            data=[{"phase": k, "trial_count": v} for k, v in counts.items()],
        )


ONE_DRUG = SearchPlan(groups=[SearchGroup(label="Pembrolizumab", intervention="pembrolizumab")], interpretation="Pembrolizumab trials")
TWO_DRUGS = SearchPlan(
    groups=[SearchGroup(label="Nivolumab", intervention="nivolumab"), SearchGroup(label="Pembrolizumab", intervention="pembrolizumab")],
    interpretation="Nivolumab vs pembrolizumab trials",
)
BY_PHASE = ChartPlan(intent="distribution", chart_type="bar_chart", title="Trials by phase", x=Dimension.PHASE)


def make_workflow(search_plan, fetched, chart_plan=BY_PHASE):
    source = FakeSource(fetched)
    chart_planner = FakeChartPlanner(chart_plan)
    wf = QueryWorkflow(FakeSearchPlanner(search_plan), source, FakeProfiler(), chart_planner, FakeVisualizer())
    return wf, source, chart_planner


def run(wf, **request):
    return asyncio.run(wf.run(QueryRequest(query="test question", **request)))


# --- Happy path ------------------------------------------------------------------------


def test_single_group_runs_end_to_end():
    fetched = {'"pembrolizumab"': FetchResult(trials=[trial(1), trial(2, "PHASE3")], total_matched=2)}
    wf, source, chart_planner = make_workflow(ONE_DRUG, fetched)

    resp = run(wf)

    assert len(source.calls) == 1
    assert source.calls[0].intervention == '"pembrolizumab"'  # sent as a phrase
    assert chart_planner.seen_profile.trials_fetched == 2  # agent 2 saw the data profile
    assert resp.meta.total_trials_matched == 2
    assert resp.meta.trials_analyzed == 2
    assert resp.meta.interpretation == "Pembrolizumab trials"
    assert resp.vega_lite is not None


def test_comparison_fetches_each_group():
    fetched = {
        '"nivolumab"': FetchResult(trials=[trial(1)], total_matched=1),
        '"pembrolizumab"': FetchResult(trials=[trial(2), trial(3)], total_matched=2),
    }
    wf, source, chart_planner = make_workflow(TWO_DRUGS, fetched)

    run(wf)

    assert sorted(p.intervention for p in source.calls) == ['"nivolumab"', '"pembrolizumab"']
    assert chart_planner.seen_profile.group_sizes == {"Nivolumab": 1, "Pembrolizumab": 2}


# --- User filters vs planner -------------------------------------------------------------


def test_structured_fields_override_the_plan():
    fetched = {'"Keytruda"': FetchResult(trials=[trial(1)], total_matched=1)}
    wf, source, _ = make_workflow(ONE_DRUG, fetched)

    resp = run(wf, drug_name="Keytruda", trial_phase=["PHASE3"], start_year=2015)

    params = source.calls[0]
    assert params.intervention == '"Keytruda"'
    assert params.advanced == "AREA[Phase](PHASE3) AND AREA[StartDate]RANGE[2015-01-01,MAX]"
    assert resp.meta.filters_applied["phases"] == ["PHASE3"]


def test_plan_that_honours_user_filters_is_left_alone(caplog):
    honouring = SearchPlan(
        groups=[SearchGroup(label="Keytruda", intervention="keytruda")],  # case differs: still a match
        phases=["PHASE3"],
        interpretation="Keytruda phase 3 trials",
    )
    fetched = {'"keytruda"': FetchResult(trials=[trial(1)], total_matched=1)}
    wf, source, _ = make_workflow(honouring, fetched)

    with caplog.at_level("INFO", logger="cheiron.workflow.translate"):
        run(wf, drug_name="Keytruda", trial_phase=["PHASE3"])

    assert source.calls[0].intervention == '"keytruda"'  # planner's value kept
    assert "planner correction" not in caplog.text


def test_dropped_user_filter_is_restored_and_logged(caplog):
    fetched = {'"pembrolizumab"': FetchResult(trials=[trial(1)], total_matched=1)}
    wf, source, _ = make_workflow(ONE_DRUG, fetched)  # plan has no phase filter

    with caplog.at_level("INFO", logger="cheiron.workflow.translate"):
        resp = run(wf, trial_phase=["PHASE3"])

    assert source.calls[0].advanced == "AREA[Phase](PHASE3)"
    assert "planner correction: phases" in caplog.text
    assert resp.meta.warnings == []  # the user got what they asked for: nothing to warn about


def test_structured_field_does_not_erase_a_comparison():
    fetched = {
        '"nivolumab"': FetchResult(trials=[trial(1)], total_matched=1),
        '"pembrolizumab"': FetchResult(trials=[trial(2)], total_matched=1),
    }
    wf, source, _ = make_workflow(TWO_DRUGS, fetched)

    resp = run(wf, drug_name="Keytruda")

    assert len({p.intervention for p in source.calls}) == 2
    assert any("Ignored drug_name" in w for w in resp.meta.warnings)


# --- Warnings and errors ---------------------------------------------------------------------


def test_truncated_fetch_is_reported():
    fetched = {'"pembrolizumab"': FetchResult(trials=[trial(1)], total_matched=900)}
    wf, _, _ = make_workflow(ONE_DRUG, fetched)

    resp = run(wf)

    assert resp.meta.total_trials_matched == 900
    assert resp.meta.trials_analyzed == 1
    assert any("analyzed 1 of 900" in w for w in resp.meta.warnings)


def test_no_trials_raises_no_results():
    wf, _, _ = make_workflow(ONE_DRUG, {})
    with pytest.raises(NoResults) as exc:
        run(wf)
    assert exc.value.to_response().error == "no_results"


def test_grouping_by_side_without_a_comparison_is_rejected():
    by_group = ChartPlan(
        intent="magnitude", chart_type="grouped_bar_chart", title="t", x=Dimension.PHASE, series=Dimension.GROUP
    )
    fetched = {'"pembrolizumab"': FetchResult(trials=[trial(1)], total_matched=1)}
    wf, _, _ = make_workflow(ONE_DRUG, fetched, by_group)
    with pytest.raises(UnsupportedQuery):
        run(wf)


def test_mostly_missing_dimension_is_warned():
    by_year = ChartPlan(intent="change_over_time", chart_type="time_series", title="t", x=Dimension.START_YEAR)
    fetched = {'"pembrolizumab"': FetchResult(trials=[trial(1), trial(2, year=None)], total_matched=2)}
    wf, _, _ = make_workflow(ONE_DRUG, fetched, by_year)

    resp = run(wf)

    assert any("have no start_year" in w for w in resp.meta.warnings)


def test_dimension_with_no_values_is_rejected():
    by_year = ChartPlan(intent="change_over_time", chart_type="time_series", title="t", x=Dimension.START_YEAR)
    fetched = {'"pembrolizumab"': FetchResult(trials=[trial(1, year=None)], total_matched=1)}
    wf, _, _ = make_workflow(ONE_DRUG, fetched, by_year)
    with pytest.raises(UnsupportedQuery):
        run(wf)


# --- Plans and translation ------------------------------------------------------------------


def test_chart_plan_must_fit_catalog():
    with pytest.raises(ValueError, match="does not fit"):
        ChartPlan(intent="ranking", chart_type="scatter_plot", title="t", x=Dimension.ENROLLMENT)
    with pytest.raises(ValueError, match="needs a series"):
        ChartPlan(intent="relationship", chart_type="network_graph", title="t", x=Dimension.SPONSOR)


def test_phrase_quotes_plain_text_only():
    assert phrase("multiple sclerosis") == '"multiple sclerosis"'
    assert phrase("asthma OR COPD") == "asthma OR COPD"
    assert phrase('"already quoted"') == '"already quoted"'
