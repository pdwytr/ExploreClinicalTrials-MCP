import pytest
from pydantic import ValidationError

from cheiron.models import QueryRequest, QueryResponse


# --- Request -------------------------------------------------------------------


def test_brief_example_request_is_valid():
    req = QueryRequest.model_validate(
        {"query": "How has the number of trials for this drug changed over time?", "drug_name": "Pembrolizumab"}
    )
    assert req.filters() == {"drug_name": "Pembrolizumab"}


def test_query_is_required():
    with pytest.raises(ValidationError):
        QueryRequest.model_validate({"drug_name": "Pembrolizumab"})


def test_unknown_field_is_rejected():
    with pytest.raises(ValidationError):
        QueryRequest.model_validate({"query": "trials by phase", "drugname": "X"})


def test_year_range_must_be_ordered():
    with pytest.raises(ValidationError):
        QueryRequest.model_validate({"query": "trials per year", "start_year": 2020, "end_year": 2015})


def test_phase_must_be_a_known_value():
    with pytest.raises(ValidationError):
        QueryRequest.model_validate({"query": "trials", "trial_phase": ["PHASE9"]})


# --- Response ------------------------------------------------------------------

META = {"interpretation": "Count of trials by phase", "total_trials_matched": 110, "trials_analyzed": 110}


def test_brief_example_bar_chart_with_citations_is_valid():
    resp = QueryResponse.model_validate(
        {
            "visualization": {
                "type": "bar_chart",
                "title": "Trials by Phase for Pembrolizumab",
                "encoding": {
                    "x": {"field": "phase", "type": "ordinal"},
                    "y": {"field": "trial_count", "type": "quantitative"},
                },
                "data": [
                    {"phase": "Phase 1", "trial_count": 32},
                    {
                        "phase": "Phase 3",
                        "trial_count": 41,
                        "citations": [{"nct_id": "NCT01234567", "excerpt": "Phase 3 randomized study..."}],
                    },
                ],
            },
            "meta": {**META, "filters_applied": {"drug_name": "Pembrolizumab"}},
        }
    )
    assert resp.visualization.type == "bar_chart"
    assert resp.visualization.data[1].citations[0].nct_id == "NCT01234567"


def test_chart_rejects_rows_missing_an_encoded_field():
    with pytest.raises(ValidationError, match="missing encoded field"):
        QueryResponse.model_validate(
            {
                "visualization": {
                    "type": "bar_chart",
                    "title": "t",
                    "encoding": {
                        "x": {"field": "phase", "type": "ordinal"},
                        "y": {"field": "trial_count", "type": "quantitative"},
                    },
                    "data": [{"phase": "Phase 1"}],
                },
                "meta": META,
            }
        )


def test_grouped_bar_requires_series():
    with pytest.raises(ValidationError, match="requires encoding.series"):
        QueryResponse.model_validate(
            {
                "visualization": {
                    "type": "grouped_bar_chart",
                    "title": "t",
                    "encoding": {
                        "x": {"field": "phase", "type": "ordinal"},
                        "y": {"field": "trial_count", "type": "quantitative"},
                    },
                    "data": [{"phase": "Phase 1", "trial_count": 3}],
                },
                "meta": META,
            }
        )


def test_network_graph_is_valid_and_rejects_dangling_edges():
    viz = {
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
    QueryResponse.model_validate({"visualization": viz, "meta": META})

    viz["data"]["edges"].append({"source": "s1", "target": "missing"})
    with pytest.raises(ValidationError, match="unknown node ids"):
        QueryResponse.model_validate({"visualization": viz, "meta": META})


def test_bad_nct_id_is_rejected():
    with pytest.raises(ValidationError):
        QueryResponse.model_validate(
            {
                "visualization": {
                    "type": "bar_chart",
                    "title": "t",
                    "encoding": {
                        "x": {"field": "phase", "type": "ordinal"},
                        "y": {"field": "trial_count", "type": "quantitative"},
                    },
                    "data": [{"phase": "P1", "trial_count": 1, "citations": [{"nct_id": "123", "excerpt": "x"}]}],
                },
                "meta": META,
            }
        )
