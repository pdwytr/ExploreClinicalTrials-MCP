"""Every chart type must produce a spec that passes the official Vega-Lite schema."""

import pytest

from studytrials.models import QueryResponse

alt = pytest.importorskip("altair")

META = {"interpretation": "i", "total_trials_matched": 1, "trials_analyzed": 1}
COUNT = {"field": "trial_count", "type": "quantitative", "title": "Trials"}
PHASE = {"field": "phase", "type": "ordinal"}
DRUG = {"field": "drug", "type": "nominal"}
CITE = [{"nct_id": "NCT01234567", "excerpt": "Phase 1 study"}]

CASES = {
    "bar_chart": ("ranking", {"x": {**PHASE, "sort": "-y"}, "y": COUNT}, [{"phase": "Phase 1", "trial_count": 3, "citations": CITE}]),
    "grouped_bar_chart": (
        "magnitude",
        {"x": PHASE, "y": COUNT, "color": DRUG, "xOffset": DRUG},
        [{"phase": "Phase 1", "drug": "A", "trial_count": 3}, {"phase": "Phase 1", "drug": "B", "trial_count": 5}],
    ),
    "stacked_bar_chart": (
        "part_to_whole",
        {"x": PHASE, "y": COUNT, "color": {"field": "sponsor_class", "type": "nominal"}},
        [{"phase": "Phase 1", "sponsor_class": "INDUSTRY", "trial_count": 3}],
    ),
    "time_series": (
        "change_over_time",
        {"x": {"field": "start_date", "type": "temporal", "timeUnit": "utcyear"}, "y": COUNT},
        [{"start_date": "2015-01-01", "trial_count": 4}, {"start_date": "2016-01-01", "trial_count": 9}],
    ),
    "scatter_plot": (
        "correlation",
        {"x": {"field": "duration_months", "type": "quantitative"}, "y": {"field": "enrollment", "type": "quantitative"}},
        [{"duration_months": 12, "enrollment": 300}],
    ),
    "histogram": (
        "distribution",
        {"x": {"field": "bin_start", "type": "quantitative", "bin": "binned"}, "x2": {"field": "bin_end"}, "y": COUNT},
        [{"bin_start": 0, "bin_end": 100, "trial_count": 7}],
    ),
}


@pytest.mark.parametrize("chart_type", CASES)
def test_generated_spec_is_valid_vega_lite(chart_type):
    intent, encoding, data = CASES[chart_type]
    resp = QueryResponse.model_validate(
        {
            "visualization": {"type": chart_type, "intent": intent, "title": "t", "encoding": encoding, "data": data},
            "meta": META,
        }
    )
    spec = resp.vega_lite
    alt.Chart.from_dict(spec, validate=True)  # raises if the spec breaks the Vega-Lite schema
    assert spec["data"]["values"][0] == resp.visualization.data[0].model_dump(mode="json", exclude={"nct_ids", "citations"}) | {"_row": 0}


def test_response_json_includes_vega_lite():
    intent, encoding, data = CASES["bar_chart"]
    resp = QueryResponse.model_validate(
        {"visualization": {"type": "bar_chart", "intent": intent, "title": "t", "encoding": encoding, "data": data}, "meta": META}
    )
    dumped = resp.model_dump(mode="json")
    assert dumped["vega_lite"]["mark"] == "bar"
    assert dumped["vega_lite"]["encoding"]["x"]["sort"] == "-y"
