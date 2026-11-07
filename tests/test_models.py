import pytest
from pydantic import ValidationError

from cheiron.models import Intent, QueryResponse

# Request validation lives in test_requests.py; this file covers responses.

# --- Response helpers ------------------------------------------------------------

META = {"interpretation": "Count of trials by phase", "total_trials_matched": 110, "trials_analyzed": 110}
X_PHASE = {"field": "phase", "type": "ordinal"}
Y_COUNT = {"field": "trial_count", "type": "quantitative"}


def chart(type_, intent, encoding, data):
    return {"visualization": {"type": type_, "intent": intent, "title": "t", "encoding": encoding, "data": data}, "meta": META}


# --- Charts ------------------------------------------------------------------------


def test_brief_example_bar_chart_with_citations_is_valid():
    resp = QueryResponse.model_validate(
        chart(
            "bar_chart",
            "distribution",
            {"x": {**X_PHASE, "sort": ["Phase 1", "Phase 2", "Phase 3"]}, "y": Y_COUNT},
            [
                {"phase": "Phase 1", "trial_count": 32},
                {
                    "phase": "Phase 3",
                    "trial_count": 41,
                    "citations": [{"nct_id": "NCT01234567", "excerpt": "Phase 3 randomized study..."}],
                },
            ],
        )
    )
    assert resp.visualization.data[1].citations[0].nct_id == "NCT01234567"


def test_chart_rejects_rows_missing_an_encoded_field():
    with pytest.raises(ValidationError, match="missing encoded field"):
        QueryResponse.model_validate(chart("bar_chart", "ranking", {"x": X_PHASE, "y": Y_COUNT}, [{"phase": "P1"}]))


def test_grouped_bar_requires_color_and_xoffset():
    drug = {"field": "drug", "type": "nominal"}
    row = [{"phase": "Phase 1", "drug": "A", "trial_count": 3}]
    with pytest.raises(ValidationError, match="requires encoding.color and encoding.xOffset"):
        QueryResponse.model_validate(chart("grouped_bar_chart", "magnitude", {"x": X_PHASE, "y": Y_COUNT, "color": drug}, row))
    QueryResponse.model_validate(
        chart("grouped_bar_chart", "magnitude", {"x": X_PHASE, "y": Y_COUNT, "color": drug, "xOffset": drug}, row)
    )


def test_pre_binned_histogram_requires_bin_end():
    x = {"field": "bin_start", "type": "quantitative", "bin": "binned"}
    row = [{"bin_start": 0, "bin_end": 100, "trial_count": 7}]
    with pytest.raises(ValidationError, match="requires encoding.x2"):
        QueryResponse.model_validate(chart("histogram", "distribution", {"x": x, "y": Y_COUNT}, row))


def test_histogram_accepts_ordered_bin_labels_but_not_a_plain_quantitative_x():
    row = [{"range": "0–49", "trial_count": 7}]
    ordinal = {"field": "range", "type": "ordinal", "sort": ["0–49"]}
    QueryResponse.model_validate(chart("histogram", "distribution", {"x": ordinal, "y": Y_COUNT}, row))
    plain = {"field": "range", "type": "quantitative"}
    with pytest.raises(ValidationError, match="histogram requires"):
        QueryResponse.model_validate(chart("histogram", "distribution", {"x": plain, "y": Y_COUNT}, row))


def test_bad_nct_id_is_rejected():
    with pytest.raises(ValidationError):
        QueryResponse.model_validate(
            chart(
                "bar_chart",
                "ranking",
                {"x": X_PHASE, "y": Y_COUNT},
                [{"phase": "P1", "trial_count": 1, "citations": [{"nct_id": "123", "excerpt": "x"}]}],
            )
        )


def test_vega_lite_names_are_accepted_and_emitted():
    year = {"field": "start_date", "type": "temporal", "timeUnit": "utcyear"}
    resp = QueryResponse.model_validate(
        chart("time_series", "change_over_time", {"x": year, "y": Y_COUNT}, [{"start_date": "2015-01-01", "trial_count": 4}])
    )
    dumped = resp.model_dump(mode="json")
    assert dumped["visualization"]["encoding"]["x"]["timeUnit"] == "utcyear"
    assert "time_unit" not in dumped["visualization"]["encoding"]["x"]


# --- Network ---------------------------------------------------------------------

NETWORK = {
    "type": "network_graph",
    "title": "Sponsors and drugs",
    "data": {
        "nodes": [
            {"id": "d1", "label": "Pembrolizumab", "group": "drug"},
            {"id": "s1", "label": "Merck", "group": "sponsor"},
        ],
        "edges": [{"source": "s1", "target": "d1", "weight": 12}],
    },
}


def test_network_graph_is_valid_and_has_no_vega_lite():
    resp = QueryResponse.model_validate({"visualization": NETWORK, "meta": META})
    assert resp.visualization.intent == Intent.RELATIONSHIP
    assert resp.vega_lite is None


def test_network_rejects_dangling_edges():
    bad = {**NETWORK, "data": {**NETWORK["data"], "edges": [{"source": "s1", "target": "missing"}]}}
    with pytest.raises(ValidationError, match="unknown node ids"):
        QueryResponse.model_validate({"visualization": bad, "meta": META})


def test_network_data_round_trips_through_networkx():
    nx = pytest.importorskip("networkx")
    resp = QueryResponse.model_validate({"visualization": NETWORK, "meta": META})
    graph = nx.node_link_graph(resp.visualization.data.model_dump(mode="json"), edges="edges")
    assert graph.number_of_nodes() == 2
    assert graph["s1"]["d1"]["weight"] == 12
