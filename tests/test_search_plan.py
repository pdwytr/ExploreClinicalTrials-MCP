"""SearchPlan (the API searches the planner writes) and how code prepares them."""

import pytest
from pydantic import TypeAdapter, ValidationError

from cheiron.models.request import QueryRequest
from cheiron.workflow import SearchPlan, SearchPlannerOutput, Unanswerable
from cheiron.workflow.translate import apply_request_filters, filters_summary, phrase


def plan(*searches: tuple[str, dict], rationale: str = "r") -> SearchPlan:
    return SearchPlan.model_validate(
        {"searches": [{"label": label, "params": params} for label, params in searches], "rationale": rationale}
    )


def request(**fields) -> QueryRequest:
    return QueryRequest(query="test question", **fields)


# --- What the planner may write ----------------------------------------------------------


def test_valid_plan():
    p = plan(("MS", {"query.cond": '"multiple sclerosis"', "filter.advanced": "AREA[Phase](PHASE2 OR PHASE3)"}))
    assert p.searches[0].params["query.cond"] == '"multiple sclerosis"'
    assert not p.is_comparison


def test_unknown_or_reserved_params_are_rejected():
    with pytest.raises(ValidationError, match="unknown or reserved"):
        plan(("x", {"query.drug": "aspirin"}))
    with pytest.raises(ValidationError, match="unknown or reserved"):
        plan(("x", {"query.cond": "asthma", "pageSize": "10"}))


def test_a_search_needs_at_least_one_param():
    with pytest.raises(ValidationError):
        plan(("x", {}))


def test_labels_unique_and_compared_searches_differ():
    with pytest.raises(ValidationError, match="labels must be unique"):
        plan(("Drug", {"query.intr": "a"}), ("drug", {"query.intr": "b"}))
    with pytest.raises(ValidationError, match="must differ"):
        plan(("A", {"query.intr": "a"}), ("B", {"query.intr": "a"}))


def test_planner_output_is_a_plan_or_unanswerable():
    adapter = TypeAdapter(SearchPlannerOutput)
    decided = adapter.validate_python(
        {"kind": "search", "plan": {"searches": [{"label": "x", "params": {"query.cond": "asthma"}}], "rationale": "r"}}
    )
    assert decided.plan.searches[0].label == "x"
    refused = adapter.validate_python({"kind": "unanswerable", "reason": "Efficacy is not in registry records."})
    assert isinstance(refused, Unanswerable)


# --- Adding the user's structured filters ---------------------------------------------------


def test_no_user_filters_leaves_searches_unchanged():
    prepared, warnings = apply_request_filters(plan(("x", {"query.cond": "asthma"})), request())
    assert prepared[0][1].search == {"query.cond": "asthma"}
    assert warnings == []


def test_text_filter_is_anded_unless_already_present():
    p = plan(("x", {"query.intr": '"pembrolizumab"'}))
    prepared, _ = apply_request_filters(p, request(condition="melanoma", drug_name="Pembrolizumab"))
    assert prepared[0][1].search == {
        "query.intr": '"pembrolizumab"',  # already searched (case-insensitive): left alone
        "query.cond": '"melanoma"',  # added as a quoted phrase
    }


def test_phase_and_years_are_anded_onto_advanced_filter():
    p = plan(("x", {"query.cond": "asthma", "filter.advanced": "AREA[StudyType]INTERVENTIONAL"}))
    prepared, _ = apply_request_filters(p, request(trial_phase=["PHASE3"], start_year=2015))
    assert prepared[0][1].search["filter.advanced"] == (
        "(AREA[StudyType]INTERVENTIONAL) AND AREA[Phase](PHASE3) AND AREA[StartDate]RANGE[2015-01-01,MAX]"
    )


def test_user_statuses_replace_planner_statuses():
    p = plan(("x", {"query.cond": "asthma", "filter.overallStatus": "COMPLETED"}))
    prepared, _ = apply_request_filters(p, request(recruitment_status=["RECRUITING"]))
    assert prepared[0][1].search["filter.overallStatus"] == "RECRUITING"


def test_text_filter_does_not_erase_a_comparison():
    p = plan(("Nivolumab", {"query.intr": "nivolumab"}), ("Pembrolizumab", {"query.intr": "pembrolizumab"}))
    prepared, warnings = apply_request_filters(p, request(drug_name="Keytruda"))
    assert [params.search["query.intr"] for _, params in prepared] == ["nivolumab", "pembrolizumab"]
    assert "Ignored drug_name" in warnings[0]


def test_filters_apply_to_every_search():
    p = plan(("A", {"query.intr": "nivolumab"}), ("B", {"query.intr": "pembrolizumab"}))
    prepared, _ = apply_request_filters(p, request(trial_phase=["PHASE3"]))
    assert {params.search["filter.advanced"] for _, params in prepared} == {"AREA[Phase](PHASE3)"}


def test_filters_summary_shows_the_exact_searches():
    prepared, _ = apply_request_filters(plan(("x", {"query.cond": "asthma"})), request())
    assert filters_summary(prepared) == {"searches": [{"label": "x", "params": {"query.cond": "asthma"}}]}


def test_phrase_quotes_user_values():
    assert phrase("multiple sclerosis") == '"multiple sclerosis"'
    assert phrase('say "hi"') == '"say hi"'
