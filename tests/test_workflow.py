"""The workflow around the agent: fetching a plan, the data-version guard, and assembling the response.
The agent is a fake that behaves like QueryAgent (fetch -> profile -> check chart); the real
agent's tool loop is tested in test_query_agent.py."""

import asyncio

import pytest

from cheiron.fetch.models import SNAPSHOT_API_VERSION, DataVersion, Trial
from cheiron.models.request import QueryRequest
from cheiron.workflow import (
    AgentResult,
    ChartPlan,
    Dimension,
    FetchResult,
    InvalidSearch,
    NoResults,
    QueryWorkflow,
    SearchPlan,
    UpstreamError,
)
from cheiron.workflow import pipeline
from cheiron.workflow.pipeline import check_chart_plan
from cheiron.workflow.profile import build_profile

# --- Fakes ---------------------------------------------------------------------------


def version(day: int = 6, api: str = SNAPSHOT_API_VERSION) -> DataVersion:
    return DataVersion(api_version=api, data_timestamp=f"2026-11-{day:02d}T10:00:05")


def trial(n: int, phase: str = "PHASE2", year: int | None = 2020) -> Trial:
    return Trial(nct_id=f"NCT{n:08d}", phases=[phase], start_date=f"{year}-01-01" if year else None)


def search_plan(*interventions: str) -> SearchPlan:
    return SearchPlan(
        steps=[{"endpoint": "studies", "label": i.title(), "params": {"query.intr": i}} for i in interventions],
        rationale=f"Trials of {' vs '.join(interventions)}",
    )


class FakeSource:
    """Canned results keyed by the query.intr searched; records every call.
    `versions` are returned by successive data_version() calls (the last one repeats)."""

    def __init__(self, by_intervention: dict[str, FetchResult | Exception], versions=None):
        self.by_intervention = by_intervention
        self.calls = []
        self.versions = list(versions or [version()])

    async def data_version(self):
        return self.versions.pop(0) if len(self.versions) > 1 else self.versions[0]

    async def search(self, params, limit, on_progress=None):
        self.calls.append(params)
        result = self.by_intervention.get(params.search.get("query.intr"), FetchResult(trials=[], total_matched=0))
        if isinstance(result, Exception):
            raise result
        if on_progress:
            on_progress(len(result.trials), result.total_matched)
        return result


class FakeAgent:
    """Does what QueryAgent does with its tools: fetch the plan, profile it, check the chart."""

    def __init__(self, plan: SearchPlan, chart: ChartPlan):
        self.plan, self.chart = plan, chart

    async def decide(self, request, fetch):
        outcome = await fetch(self.plan)
        profile = build_profile(outcome.trials_by_group, outcome.total_matched)
        warnings = check_chart_plan(self.chart, outcome.plan, profile)
        return AgentResult(self.chart, outcome, profile, warnings, ["ctgov-search", "chart-planning"], [])


BY_PHASE = ChartPlan(intent="distribution", chart_type="bar_chart", title="Trials by phase", x=Dimension.PHASE)
PHASE_BY_DRUG = ChartPlan(
    intent="magnitude", chart_type="grouped_bar_chart", title="Phases by drug", x=Dimension.PHASE, series=Dimension.GROUP
)
FOUND = FetchResult(trials=[trial(1), trial(2, "PHASE3")], total_matched=2)


def make_workflow(plan, fetched, chart=BY_PHASE, versions=None):
    source = FakeSource(fetched, versions)
    return QueryWorkflow(FakeAgent(plan, chart), source), source


def run(wf, progress=None, **request):
    return asyncio.run(wf.run(QueryRequest(query="test question", **request), progress))


# --- End to end --------------------------------------------------------------------------


def test_run_returns_a_full_response():
    wf, _ = make_workflow(search_plan("pembrolizumab"), {"pembrolizumab": FOUND})

    response, result = run(wf)

    assert [(r.phase, r.trial_count) for r in response.visualization.data] == [("PHASE2", 1), ("PHASE3", 1)]
    assert response.meta.interpretation == "Trials of pembrolizumab"
    assert response.meta.filters_applied == {
        "steps": [{"label": "Pembrolizumab", "endpoint": "studies", "params": {"query.intr": "pembrolizumab"}}]
    }
    assert response.meta.total_trials_matched == 2 and response.meta.trials_analyzed == 2
    assert response.meta.data_as_of.isoformat() == "2026-11-06T10:00:05"
    assert "Counts are distinct trials." in response.meta.assumptions
    assert response.vega_lite["mark"] == "bar"
    assert result.outcome.trials_fetched == 2


def test_comparison_is_charted_by_side_with_overlap_noted():
    fetched = {"nivolumab": FetchResult(trials=[trial(1)], total_matched=1), "pembrolizumab": FOUND}
    wf, source = make_workflow(search_plan("nivolumab", "pembrolizumab"), fetched, PHASE_BY_DRUG)

    response, _ = run(wf)

    assert sorted(p.search["query.intr"] for p in source.calls) == ["nivolumab", "pembrolizumab"]
    assert {r.group for r in response.visualization.data} == {"Nivolumab", "Pembrolizumab"}
    assert any("counted in each" in a for a in response.meta.assumptions)
    assert any("several values of phase" in a for a in response.meta.assumptions)


def test_user_filters_reach_the_api():
    wf, source = make_workflow(search_plan("pembrolizumab"), {"pembrolizumab": FOUND})
    run(wf, trial_phase=["PHASE3"])
    assert source.calls[0].search["filter.advanced"] == "AREA[Phase](PHASE3)"


def test_progress_is_reported_through_the_stages():
    fetched = {"nivolumab": FetchResult(trials=[trial(1)], total_matched=1), "pembrolizumab": FOUND}
    wf, _ = make_workflow(search_plan("nivolumab", "pembrolizumab"), fetched, PHASE_BY_DRUG)
    seen = []

    run(wf, progress=seen.append)

    assert seen[0].stage == "planning" and seen[-1].stage == "building"
    fetching = [p for p in seen if p.stage == "fetching"]
    assert fetching[-1].trials_fetched == 3 and fetching[-1].trials_total == 3  # summed across both searches


# --- fetch_plan: what the agent's fetch_data tool calls ------------------------------------------


def fetch(wf, plan, **request):
    return asyncio.run(wf.fetch_plan(plan, QueryRequest(query="test question", **request)))


def test_no_trials_raises_no_results_with_a_message_for_the_agent():
    wf, _ = make_workflow(search_plan("pembrolizmab"), {})
    with pytest.raises(NoResults, match="No trials matched these steps"):
        fetch(wf, search_plan("pembrolizmab"))


def test_api_rejection_raises_invalid_search_with_the_api_message():
    wf, _ = make_workflow(search_plan("x"), {"x": InvalidSearch("unbalanced parenthesis")})
    with pytest.raises(InvalidSearch, match="The plan was rejected: unbalanced parenthesis"):
        fetch(wf, search_plan("x"))


def test_truncated_fetch_is_reported():
    big = FetchResult(trials=[trial(1)], total_matched=900)
    wf, _ = make_workflow(search_plan("pembrolizumab"), {"pembrolizumab": big})
    outcome = fetch(wf, search_plan("pembrolizumab"))
    assert any("analyzed 1 of 900" in w for w in outcome.warnings)


# --- Data version ---------------------------------------------------------------------------


def test_data_refreshed_mid_fetch_is_fetched_again():
    # before=Nov 6, after=Nov 7 (refreshed!) -> redo: before=Nov 7, after=Nov 7
    wf, source = make_workflow(
        search_plan("pembrolizumab"), {"pembrolizumab": FOUND}, versions=[version(6), version(7), version(7)]
    )
    response, _ = run(wf)
    assert len(source.calls) == 2  # the search ran twice
    assert response.meta.data_as_of.day == 7  # one consistent version


def test_data_changing_on_every_attempt_raises():
    versions = [version(6), version(7), version(8), version(9)]
    wf, _ = make_workflow(search_plan("pembrolizumab"), {"pembrolizumab": FOUND}, versions=versions)
    with pytest.raises(UpstreamError, match="data changed"):
        run(wf)


def test_newer_api_version_warns_that_docs_are_outdated(caplog, monkeypatch):
    monkeypatch.setattr(pipeline, "_docs_warning_logged", False)
    wf, _ = make_workflow(search_plan("pembrolizumab"), {"pembrolizumab": FOUND}, versions=[version(api="2.1.0")])

    with caplog.at_level("WARNING", logger="cheiron.workflow.pipeline"):
        response, _ = run(wf)

    assert "API is 2.1.0 but docs/ctgov and the ctgov-search skill describe" in caplog.text
    assert response.meta.api_version == "2.1.0"


# --- Chart checks (the agent's answer is checked against the data) ----------------------------------


def test_grouping_by_side_without_a_comparison_is_rejected():
    wf, _ = make_workflow(search_plan("pembrolizumab"), {"pembrolizumab": FOUND}, PHASE_BY_DRUG)
    with pytest.raises(Exception, match="only one search"):
        run(wf)


def test_mostly_missing_dimension_is_warned_in_meta():
    by_year = ChartPlan(intent="change_over_time", chart_type="time_series", title="t", x=Dimension.START_YEAR)
    fetched = {"pembrolizumab": FetchResult(trials=[trial(1), trial(2, year=None)], total_matched=2)}
    wf, _ = make_workflow(search_plan("pembrolizumab"), fetched, by_year)

    response, _ = run(wf)

    assert any("have no start_year" in w for w in response.meta.warnings)


def test_chart_plan_structural_rules():
    with pytest.raises(ValueError, match="scatter_plot needs two numeric fields"):
        ChartPlan(intent="correlation", chart_type="scatter_plot", title="t", x=Dimension.ENROLLMENT)
    with pytest.raises(ValueError, match="needs a series"):
        ChartPlan(intent="relationship", chart_type="network_graph", title="t", x=Dimension.SPONSOR)
