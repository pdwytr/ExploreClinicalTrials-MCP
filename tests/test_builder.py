"""The deterministic visualizer: counts, ordering, citations and every chart shape."""

from datetime import date

import altair as alt
import pytest
from pydantic import ValidationError

from cheiron.fetch.models import Intervention, Trial
from cheiron.models.response import Meta, QueryResponse
from cheiron.visualize.builder import CITATIONS_PER_DATUM, FIELD_PATHS, build_visualization
from cheiron.workflow.errors import UnsupportedQuery
from cheiron.workflow.pipeline import check_chart_plan
from cheiron.workflow.plans import ChartPlan, Dimension, SearchPlan
from cheiron.workflow.profile import build_profile


def trial(n: int, **fields) -> Trial:
    return Trial(nct_id=f"NCT{n:08d}", **fields)


def plan(**fields) -> ChartPlan:
    return ChartPlan(title="t", **fields)


def as_response(viz):
    """Every built visualization must pass the response contract, and its Vega-Lite the official schema."""
    meta = Meta(interpretation="i", total_trials_matched=1, trials_analyzed=1)
    response = QueryResponse(visualization=viz, meta=meta)
    if response.vega_lite is not None:
        alt.Chart.from_dict(response.vega_lite, validate=True)
    return response


# --- Bar charts -------------------------------------------------------------------------------


def test_bar_by_phase_counts_distinct_trials_in_clinical_order():
    trials = [trial(1, phases=["PHASE2", "PHASE3"]), trial(2, phases=["PHASE3"]), trial(3, phases=["PHASE1"]), trial(4)]
    viz, warnings = build_visualization({"All": trials}, plan(intent="distribution", chart_type="bar_chart", x=Dimension.PHASE))

    assert [(r.phase, r.trial_count) for r in viz.data] == [("PHASE1", 1), ("PHASE2", 1), ("PHASE3", 2)]
    assert warnings == []
    as_response(viz)


def test_each_datum_cites_its_trials_with_exact_field_and_value():
    trials = [trial(n, lead_sponsor="Merck") for n in range(8)]
    viz, _ = build_visualization({"All": trials}, plan(intent="ranking", chart_type="bar_chart", x=Dimension.SPONSOR))

    row = viz.data[0]
    assert row.trial_count == 8 and len(row.citations) == CITATIONS_PER_DATUM
    assert row.citations[0].model_dump() == {
        "nct_id": "NCT00000000",
        "excerpt": "Merck",
        "field": FIELD_PATHS[Dimension.SPONSOR],
    }


def test_many_categories_are_cut_to_the_top_with_a_warning():
    trials = [trial(n, countries=[f"Country {n % 40}"]) for n in range(400)]
    viz, warnings = build_visualization({"All": trials}, plan(intent="ranking", chart_type="bar_chart", x=Dimension.COUNTRY))
    assert len(viz.data) == 25
    assert "15 smaller categories" in warnings[0]
    viz, warnings = build_visualization(
        {"All": trials}, plan(intent="ranking", chart_type="bar_chart", x=Dimension.COUNTRY, top_n=5)
    )
    assert len(viz.data) == 5


def test_comparison_grouped_bar_includes_zero_cells():
    data = {"Nivolumab": [trial(1, phases=["PHASE3"])], "Pembrolizumab": [trial(2, phases=["PHASE2"])]}
    viz, _ = build_visualization(
        data, plan(intent="magnitude", chart_type="grouped_bar_chart", x=Dimension.PHASE, series=Dimension.GROUP)
    )
    cells = {(r.phase, r.group): r.trial_count for r in viz.data}
    assert cells == {("PHASE2", "Nivolumab"): 0, ("PHASE2", "Pembrolizumab"): 1, ("PHASE3", "Nivolumab"): 1, ("PHASE3", "Pembrolizumab"): 0}
    assert viz.encoding.x_offset.field == "group"
    as_response(viz)


# --- Time, histogram, network -------------------------------------------------------------------


def test_time_series_fills_empty_years_with_zero():
    trials = [trial(1, start_date=date(2015, 3, 1)), trial(2, start_date=date(2018, 1, 1)), trial(3)]
    viz, _ = build_visualization(
        {"All": trials}, plan(intent="change_over_time", chart_type="time_series", x=Dimension.START_YEAR)
    )
    assert [(r.start_year, r.trial_count) for r in viz.data] == [
        ("2015-01-01", 1), ("2016-01-01", 0), ("2017-01-01", 0), ("2018-01-01", 1)
    ]  # fmt: skip
    assert viz.data[0].citations[0].excerpt == "2015-03-01"  # the exact date, not just the year
    as_response(viz)


def test_date_citations_quote_the_registry_text_not_the_padded_date():
    # The registry gives year-month dates ("2018-03"); they are padded to the 1st for bucketing,
    # but a citation must quote the API value exactly.
    trials = [trial(1, start_date="2018-03"), trial(2, start_date="2019-07-15"), trial(3, completion_date="2020-11")]
    starts, _ = build_visualization(
        {"All": trials}, plan(intent="change_over_time", chart_type="time_series", x=Dimension.START_YEAR)
    )
    assert [c.excerpt for r in starts.data for c in r.citations] == ["2018-03", "2019-07-15"]
    ends, _ = build_visualization(
        {"All": trials}, plan(intent="change_over_time", chart_type="time_series", x=Dimension.COMPLETION_YEAR)
    )
    assert [c.excerpt for r in ends.data for c in r.citations] == ["2020-11"]


def test_histogram_bins_enrollment():
    trials = [trial(1, enrollment=10), trial(2, enrollment=60), trial(3, enrollment=70), trial(4, enrollment=3000)]
    viz, _ = build_visualization({"All": trials}, plan(intent="distribution", chart_type="histogram", x=Dimension.ENROLLMENT))
    counts = {(r.enrollment_from, r.enrollment_to): r.trial_count for r in viz.data}
    assert counts[(0, 50)] == 1 and counts[(50, 100)] == 2 and counts[(2500, 3001)] == 1
    assert sum(counts.values()) == 4
    as_response(viz)


def test_histogram_bins_get_equal_width_ordered_labels_and_an_open_last_bin():
    # Bin edges grow geometrically and enrollment is heavily skewed: on a linear axis the
    # top bin (10,000 .. max) would fill the chart, so bins are drawn as ordered labels.
    trials = [trial(1, enrollment=10), trial(2, enrollment=60), trial(3, enrollment=12000), trial(4, enrollment=5_132_201)]
    viz, _ = build_visualization({"All": trials}, plan(intent="distribution", chart_type="histogram", x=Dimension.ENROLLMENT))
    x = viz.encoding.x
    assert x.field == "enrollment_range" and x.type.value == "ordinal" and not x.bin and viz.encoding.x2 is None
    labels = [r.enrollment_range for r in viz.data]
    assert labels == ["0–49", "50–99", "100–249", "250–499", "500–999", "1,000–2,499", "2,500–4,999", "5,000–9,999", "10,000+"]
    assert x.sort == labels
    last = viz.data[-1]
    assert (last.enrollment_from, last.enrollment_to, last.trial_count) == (10000, None, 2)
    as_response(viz)


def test_histogram_last_bin_ends_at_the_largest_value_below_the_top_edge():
    viz, _ = build_visualization(
        {"All": [trial(1, enrollment=0), trial(2, enrollment=3000)]},
        plan(intent="distribution", chart_type="histogram", x=Dimension.ENROLLMENT),
    )
    assert viz.data[0].enrollment_range == "0–49"
    assert (viz.data[-1].enrollment_range, viz.data[-1].enrollment_to) == ("2,500–3,000", 3001)


def test_cooccurrence_network_links_values_within_one_trial():
    drugs = lambda *names: [Intervention(name=n, type="DRUG") for n in names]  # noqa: E731
    trials = [trial(1, interventions=drugs("A", "B")), trial(2, interventions=drugs("A", "B", "C")), trial(3, interventions=drugs("A"))]
    viz, _ = build_visualization(
        {"All": trials},
        plan(intent="relationship", chart_type="network_graph", x=Dimension.INTERVENTION, series=Dimension.INTERVENTION),
    )
    weights = {(e.source, e.target): e.weight for e in viz.data.edges}
    assert weights[("intervention:A", "intervention:B")] == 2
    assert weights[("intervention:A", "intervention:C")] == 1
    assert {n.label: n.size for n in viz.data.nodes} == {"A": 3, "B": 2, "C": 1}
    as_response(viz)


def test_bipartite_network_links_two_fields():
    trials = [trial(1, lead_sponsor="Merck", interventions=[Intervention(name="pembrolizumab", type="DRUG")])]
    viz, _ = build_visualization(
        {"All": trials},
        plan(intent="relationship", chart_type="network_graph", x=Dimension.SPONSOR, series=Dimension.INTERVENTION),
    )
    assert [(e.source, e.target, e.weight) for e in viz.data.edges] == [("lead_sponsor:Merck", "intervention:pembrolizumab", 1)]


def test_network_merges_values_that_differ_only_by_case_or_spacing():
    drugs = lambda *names: [Intervention(name=n, type="DRUG") for n in names]  # noqa: E731
    trials = [
        trial(1, interventions=drugs("Rituximab", "Cyclophosphamide")),
        trial(2, interventions=drugs("rituximab", "cyclophosphamide")),
        trial(3, interventions=drugs("Rituximab", "rituximab ", "Cyclophosphamide")),  # one trial, two spellings
        trial(4, interventions=drugs("Rituximab")),
    ]
    viz, _ = build_visualization(
        {"All": trials},
        plan(intent="relationship", chart_type="network_graph", x=Dimension.INTERVENTION, series=Dimension.INTERVENTION),
    )
    # one node per drug, labelled with the most frequent spelling; trial 3 counts once
    assert {n.label: n.size for n in viz.data.nodes} == {"Rituximab": 4, "Cyclophosphamide": 3}
    # no self-loop from trial 3's two spellings; one edge, three trials
    assert [(e.source, e.target, e.weight) for e in viz.data.edges] == [
        ("intervention:Cyclophosphamide", "intervention:Rituximab", 3)
    ]
    # citations still quote each trial's own spelling
    ritux = next(n for n in viz.data.nodes if n.label == "Rituximab")
    assert [(c.nct_id, c.excerpt) for c in ritux.citations][:2] == [("NCT00000001", "Rituximab"), ("NCT00000002", "rituximab")]
    as_response(viz)


def test_bar_categories_merge_values_that_differ_only_by_case():
    trials = [trial(1, conditions=["Lupus Nephritis"]), trial(2, conditions=["lupus nephritis"]), trial(3, conditions=["Lupus  Nephritis"])]
    viz, _ = build_visualization({"All": trials}, plan(intent="ranking", chart_type="bar_chart", x=Dimension.CONDITION))
    assert [(r.condition, r.trial_count) for r in viz.data] == [("Lupus Nephritis", 3)]


# --- Rules -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fields", "error"),
    [
        ({"intent": "change_over_time", "chart_type": "time_series", "x": "phase"}, "needs x = start_year"),
        ({"intent": "distribution", "chart_type": "histogram", "x": "phase"}, "needs x = enrollment"),
        ({"intent": "ranking", "chart_type": "bar_chart", "x": "enrollment"}, "as a histogram"),
        ({"intent": "magnitude", "chart_type": "grouped_bar_chart", "x": "phase", "series": "phase"}, "must differ"),
    ],
)
def test_structurally_impossible_plans_are_rejected(fields, error):
    with pytest.raises(ValidationError, match=error):
        plan(**fields)


def test_stacking_a_multi_valued_field_is_rejected():
    trials = [trial(1, phases=["PHASE1", "PHASE2"], sponsor_class="INDUSTRY")]
    profile = build_profile({"All": trials}, total_matched=1)
    chart = plan(intent="part_to_whole", chart_type="stacked_bar_chart", x=Dimension.SPONSOR_CLASS, series=Dimension.PHASE)
    search = SearchPlan(steps=[{"endpoint": "studies", "label": "All", "conditions": ["x"]}], rationale="r")
    with pytest.raises(UnsupportedQuery, match="several values per trial"):
        check_chart_plan(chart, search, profile)
