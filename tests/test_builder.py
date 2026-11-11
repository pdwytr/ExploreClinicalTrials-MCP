"""The deterministic visualizer: counts, ordering, citations and every chart shape."""

from datetime import date

import altair as alt
import pytest
from pydantic import ValidationError

from trialsight.fetch.models import Intervention, Trial
from trialsight.models.response import Meta, QueryResponse
from trialsight.visualize.builder import CITATIONS_PER_DATUM, FIELD_PATHS, build_visualization
from trialsight.workflow.errors import UnsupportedQuery
from trialsight.workflow.pipeline import check_chart_plan
from trialsight.workflow.plans import ChartPlan, Dimension, SearchPlan
from trialsight.workflow.profile import build_profile


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
    trials = [trial(n, lead_sponsor="Merck", title=f"Study {n} of drug X") for n in range(8)]
    viz, _ = build_visualization({"All": trials}, plan(intent="ranking", chart_type="bar_chart", x=Dimension.SPONSOR))

    row = viz.data[0]
    assert row.trial_count == 8 and len(row.citations) == CITATIONS_PER_DATUM
    assert row.citations[0].model_dump() == {
        "nct_id": "NCT00000000",
        "excerpt": "Merck",
        "field": FIELD_PATHS[Dimension.SPONSOR],
        "title": "Study 0 of drug X",  # the trial's title, exactly as the API gave it
    }
    assert row.nct_ids == [f"NCT{n:08d}" for n in range(8)]  # every trial behind the bar, not just the cited 5


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


# --- Display names for coded values ---------------------------------------------------------------


def test_coded_values_get_the_registrys_display_names():
    trials = [trial(1, phases=["PHASE2"], overall_status="ACTIVE_NOT_RECRUITING"), trial(2, phases=["EARLY_PHASE1"], overall_status="RECRUITING")]
    viz, _ = build_visualization({"All": trials}, plan(intent="distribution", chart_type="bar_chart", x=Dimension.PHASE))
    assert viz.encoding.x.labels == {"EARLY_PHASE1": "Early Phase 1", "PHASE2": "Phase 2"}  # only values shown
    assert {r.phase for r in viz.data} == {"EARLY_PHASE1", "PHASE2"}  # rows keep the codes
    spec = as_response(viz).vega_lite
    assert "labels" not in spec["encoding"]["x"]  # not a Vega-Lite property
    assert spec["encoding"]["x"]["axis"]["labelExpr"].startswith('{"EARLY_PHASE1": "Early Phase 1"')
    status, _ = build_visualization({"All": trials}, plan(intent="distribution", chart_type="bar_chart", x=Dimension.STATUS))
    assert status.encoding.x.labels["ACTIVE_NOT_RECRUITING"] == "Active, not recruiting"


def test_free_text_fields_get_no_labels():
    viz, _ = build_visualization(
        {"All": [trial(1, lead_sponsor="Pfizer")]}, plan(intent="ranking", chart_type="bar_chart", x=Dimension.SPONSOR)
    )
    assert viz.encoding.x.labels is None


def test_a_coded_series_is_labelled_in_the_legend():
    trials = [trial(1, phases=["PHASE3"], sponsor_class="INDUSTRY"), trial(2, phases=["PHASE2"], sponsor_class="OTHER_GOV")]
    viz, _ = build_visualization(
        {"All": trials},
        plan(intent="part_to_whole", chart_type="stacked_bar_chart", x=Dimension.STATUS, series=Dimension.SPONSOR_CLASS),
    ) if False else build_visualization(
        {"All": trials}, plan(intent="magnitude", chart_type="grouped_bar_chart", x=Dimension.PHASE, series=Dimension.SPONSOR_CLASS)
    )
    assert viz.encoding.color.labels == {"INDUSTRY": "Industry", "OTHER_GOV": "Other government"}  # registry gives only codes
    assert "labelExpr" in as_response(viz).vega_lite["encoding"]["color"]["legend"]


def test_network_groups_get_display_names():
    trials = [trial(1, lead_sponsor="Pfizer", interventions=[Intervention(name="Drug A")])]
    viz, _ = build_visualization(
        {"All": trials}, plan(intent="relationship", chart_type="network_graph", x=Dimension.SPONSOR, series=Dimension.INTERVENTION)
    )
    assert viz.encoding.group_labels == {"intervention": "Intervention", "lead_sponsor": "Lead sponsor"}


# --- Shares (percent of trials) --------------------------------------------------------------------


def test_share_without_series_is_a_share_of_all_charted_trials():
    # g08: "What percentage of Alzheimer's trials are industry-sponsored?"
    trials = [trial(1, sponsor_class="INDUSTRY"), trial(2, sponsor_class="INDUSTRY"), trial(3, sponsor_class="OTHER"), trial(4, sponsor_class="NIH")]
    viz, _ = build_visualization({"All": trials}, plan(intent="part_to_whole", chart_type="bar_chart", x=Dimension.SPONSOR_CLASS, measure="share"))
    rows = {r.sponsor_class: (r.percent, r.trial_count, r.of_trials) for r in viz.data}
    assert rows["INDUSTRY"] == (50.0, 2, 4) and rows["OTHER"] == (25.0, 1, 4)
    assert viz.encoding.y.field == "percent"
    as_response(viz)


def test_share_with_a_series_is_within_each_x_category():
    # x2: "What share of lung cancer trials in each phase are industry-sponsored?"
    trials = [
        trial(1, phases=["PHASE1"], sponsor_class="INDUSTRY"), trial(2, phases=["PHASE1"], sponsor_class="OTHER"),
        trial(3, phases=["PHASE3"], sponsor_class="INDUSTRY"), trial(4, phases=["PHASE3"], sponsor_class="INDUSTRY"),
        trial(5, phases=["PHASE3"], sponsor_class="NIH"), trial(6, phases=["PHASE3"], sponsor_class="OTHER"),
    ]  # fmt: skip
    viz, _ = build_visualization(
        {"All": trials},
        plan(intent="part_to_whole", chart_type="stacked_bar_chart", x=Dimension.PHASE, series=Dimension.SPONSOR_CLASS, measure="share"),
    )
    cell = {(r.phase, r.sponsor_class): (r.percent, r.of_trials) for r in viz.data}
    assert cell[("PHASE1", "INDUSTRY")] == (50.0, 2) and cell[("PHASE3", "INDUSTRY")] == (50.0, 4)
    as_response(viz)


def test_share_in_a_comparison_is_within_each_side():
    a = [trial(1, phases=["PHASE2"]), trial(2, phases=["PHASE3"])]
    b = [trial(3, phases=["PHASE3"]), trial(4, phases=["PHASE3"]), trial(5, phases=["PHASE3"]), trial(6, phases=["PHASE1"])]
    viz, _ = build_visualization(
        {"A": a, "B": b},
        plan(intent="magnitude", chart_type="grouped_bar_chart", x=Dimension.PHASE, series=Dimension.GROUP, measure="share"),
    )
    cell = {(r.phase, r.group): r.percent for r in viz.data}
    assert cell[("PHASE3", "A")] == 50.0 and cell[("PHASE3", "B")] == 75.0  # phase mix of each side


def test_share_of_all_with_a_series_divides_every_cell_by_all_charted_trials():
    # u11: "What share of depression trials are randomized and double-blind?" Each cell is a share of
    # every charted trial, so a randomized bar's segments add up to the share that is randomized.
    trials = [
        trial(1, allocation="RANDOMIZED", masking="DOUBLE"), trial(2, allocation="RANDOMIZED", masking="QUADRUPLE"),
        trial(3, allocation="RANDOMIZED", masking="NONE"), trial(4, allocation="NA", masking="NONE"),
        trial(5),  # no design data: not charted, not in the denominator
    ]  # fmt: skip
    viz, _ = build_visualization(
        {"All": trials},
        plan(intent="part_to_whole", chart_type="stacked_bar_chart", x=Dimension.ALLOCATION, series=Dimension.MASKING,
             measure="share", share_of="all"),
    )  # fmt: skip
    cell = {(r.allocation, r.masking): (r.percent, r.of_trials) for r in viz.data}
    assert cell[("RANDOMIZED", "DOUBLE")] == (25.0, 4) and cell[("RANDOMIZED", "QUADRUPLE")] == (25.0, 4)
    assert cell[("NA", "NONE")] == (25.0, 4)
    as_response(viz)


def test_share_of_all_is_only_for_a_share_with_a_series_that_is_not_a_comparison():
    with pytest.raises(ValidationError, match="share_of"):
        plan(intent="part_to_whole", chart_type="bar_chart", x=Dimension.ALLOCATION, share_of="all")  # not a share
    with pytest.raises(ValidationError, match="share_of"):
        plan(intent="part_to_whole", chart_type="bar_chart", x=Dimension.ALLOCATION, measure="share", share_of="all")
    with pytest.raises(ValidationError, match="share_of"):
        plan(intent="magnitude", chart_type="grouped_bar_chart", x=Dimension.PHASE, series=Dimension.GROUP,
             measure="share", share_of="all")  # fmt: skip


@pytest.mark.parametrize("chart_type, x", [("histogram", Dimension.ENROLLMENT), ("network_graph", Dimension.CONDITION)])
def test_share_needs_a_bar_or_trend_chart(chart_type, x):
    with pytest.raises(ValidationError, match="share"):
        plan(intent="distribution", chart_type=chart_type, x=x, series=x if chart_type == "network_graph" else None, measure="share")


def test_design_fields_chart_with_the_registrys_names_and_cite_their_field():
    # u11-style: "what share of depression trials are randomized?"
    trials = [trial(1, allocation="RANDOMIZED", masking="QUADRUPLE"), trial(2, allocation="RANDOMIZED", masking="NONE"),
              trial(3, allocation="NON_RANDOMIZED", masking="NONE"), trial(4)]  # fmt: skip
    viz, _ = build_visualization({"All": trials}, plan(intent="part_to_whole", chart_type="bar_chart", x=Dimension.ALLOCATION, measure="share"))
    assert {r.allocation: r.percent for r in viz.data} == {"RANDOMIZED": 66.7, "NON_RANDOMIZED": 33.3}  # of the 3 with a value
    assert viz.encoding.x.labels == {"NON_RANDOMIZED": "Non-Randomized", "RANDOMIZED": "Randomized"}
    assert viz.data[0].citations[0].field == "protocolSection.designModule.designInfo.allocation"
    masking, _ = build_visualization({"All": trials}, plan(intent="distribution", chart_type="bar_chart", x=Dimension.MASKING))
    assert masking.encoding.x.labels["NONE"] == "None (Open Label)"
    as_response(viz)


# --- Scatter: enrollment against duration ----------------------------------------------------------


def finished(n: int, enrollment: int, start: str, end: str, **fields) -> Trial:
    return trial(n, enrollment=enrollment, start_date=start, primary_completion_date=end, primary_completion_date_type="ACTUAL", **fields)


def test_duration_is_start_to_actual_primary_completion():
    assert finished(1, 100, "2020-01", "2021-01").duration_months == 12.0
    planned = trial(2, start_date="2020-01-01", primary_completion_date="2023-01-01", primary_completion_date_type="ESTIMATED")
    assert planned.duration_months is None  # not finished: a plan, not a duration


def test_scatter_plots_one_cited_point_per_trial():
    # r13: "Do bigger heart failure trials take longer? Plot enrollment against duration."
    trials = [finished(1, 100, "2020-01", "2021-01"), finished(2, 900, "2018-03", "2022-03"), trial(3, enrollment=50)]
    viz, warnings = build_visualization(
        {"All": trials}, plan(intent="correlation", chart_type="scatter_plot", x=Dimension.ENROLLMENT, y=Dimension.DURATION)
    )
    assert [(r.enrollment, r.duration_months, r.nct_ids) for r in viz.data] == [(100, 12.0, ["NCT00000001"]), (900, 48.0, ["NCT00000002"])]
    assert {c.excerpt for c in viz.data[0].citations} == {"100", "2020-01", "2021-01"}  # both values, exactly as written
    assert "1 trial without both values is left out" in warnings[0]
    spec = as_response(viz).vega_lite
    assert spec["mark"] == "point" and spec["encoding"]["x"]["scale"] == {"type": "log"}  # enrollment is skewed


def test_scatter_needs_two_numeric_axes_and_numbers_stay_out_of_other_charts():
    with pytest.raises(ValidationError, match="scatter_plot needs"):
        plan(intent="correlation", chart_type="scatter_plot", x=Dimension.ENROLLMENT, y=Dimension.PHASE)
    with pytest.raises(ValidationError, match="only a scatter_plot uses y"):
        plan(intent="distribution", chart_type="bar_chart", x=Dimension.PHASE, y=Dimension.DURATION)
    with pytest.raises(ValidationError, match="numeric"):
        plan(intent="distribution", chart_type="bar_chart", x=Dimension.DURATION)


def test_scatter_leaves_out_trials_that_enrolled_no_one():
    trials = [finished(1, 0, "2020-01", "2020-01", overall_status="WITHDRAWN"), finished(2, 300, "2019-01", "2021-01")]
    viz, warnings = build_visualization(
        {"All": trials}, plan(intent="correlation", chart_type="scatter_plot", x=Dimension.ENROLLMENT, y=Dimension.DURATION)
    )
    assert [r.nct_ids for r in viz.data] == [["NCT00000002"]]
    assert "1 trial that enrolled no one" in warnings[-1]
