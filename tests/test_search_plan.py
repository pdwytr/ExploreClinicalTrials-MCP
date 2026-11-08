"""SearchPlan (the API searches the planner writes) and how code prepares them."""

import pytest
from pydantic import ValidationError

from cheiron.models.request import QueryRequest
from cheiron.workflow import SearchPlan
from cheiron.workflow.errors import InvalidSearch
from cheiron.workflow.translate import apply_request_filters, filters_summary, phrase


def plan(*searches: tuple[str, dict], rationale: str = "r") -> SearchPlan:
    return SearchPlan.model_validate(
        {"steps": [{"endpoint": "studies", "label": label, "params": params} for label, params in searches], "rationale": rationale}
    )


def request(**fields) -> QueryRequest:
    return QueryRequest(query="test question", **fields)


# --- What the planner may write ----------------------------------------------------------


def test_valid_plan():
    p = plan(("MS", {"query.cond": '"multiple sclerosis"', "filter.advanced": "AREA[Phase](PHASE2 OR PHASE3)"}))
    assert p.steps[0].params["query.cond"] == '"multiple sclerosis"'
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
        "((AREA[StudyType]INTERVENTIONAL) AND AREA[Phase](PHASE3)) AND AREA[StartDate]RANGE[2015-01-01,MAX]"
    )


def test_user_statuses_replace_planner_statuses():
    p = plan(("x", {"query.cond": "asthma", "filter.overallStatus": "COMPLETED"}))
    prepared, _ = apply_request_filters(p, request(recruitment_status=["RECRUITING"]))
    assert prepared[0][1].search["filter.overallStatus"] == "RECRUITING"


def test_text_filter_cannot_be_widened_by_an_or():
    # "already contains the user's drug" must not count: the OR would bring in other drugs' trials
    p = plan(("x", {"query.intr": '"pembrolizumab" OR "nivolumab"'}))
    prepared, _ = apply_request_filters(p, request(drug_name="Pembrolizumab"))
    assert prepared[0][1].search["query.intr"] == '("pembrolizumab" OR "nivolumab") AND "Pembrolizumab"'


def test_phase_filter_cannot_be_widened_by_an_or():
    p = plan(("x", {"query.cond": "asthma", "filter.advanced": "AREA[Phase](PHASE3) OR AREA[Phase](PHASE2)"}))
    prepared, _ = apply_request_filters(p, request(trial_phase=["PHASE3"]))
    assert prepared[0][1].search["filter.advanced"] == "(AREA[Phase](PHASE3) OR AREA[Phase](PHASE2)) AND AREA[Phase](PHASE3)"


def test_comparison_may_skip_the_user_value_only_when_it_is_a_compared_side():
    p = plan(("Nivolumab", {"query.intr": '"nivolumab"'}), ("Pembrolizumab", {"query.intr": '"pembrolizumab"'}))
    prepared, warnings = apply_request_filters(p, request(drug_name="Pembrolizumab"))
    assert [params.search["query.intr"] for _, params in prepared] == ['"nivolumab"', '"pembrolizumab"']
    assert "Ignored drug_name" in warnings[0]


def test_comparison_of_other_values_conflicts_with_the_user_value():
    # the user asked about one drug; a plan comparing two others is sent back, not intersected with it
    p = plan(("Nivolumab", {"query.intr": "nivolumab"}), ("Ipilimumab", {"query.intr": "ipilimumab"}))
    with pytest.raises(InvalidSearch, match="drug_name='Relatlimab'"):
        apply_request_filters(p, request(drug_name="Relatlimab"))


def test_structured_field_conflicting_with_the_plan_sends_the_plan_back():
    # r22 / g09: AND-ing a different term onto the planner's search answers neither question
    # ("lung cancer" AND "melanoma" is the few trials that mention both)
    with pytest.raises(InvalidSearch) as exc:
        apply_request_filters(plan(("x", {"query.cond": '"lung cancer"'})), request(condition="melanoma"))
    assert "condition='melanoma'" in exc.value.message and '"lung cancer"' in exc.value.message
    with pytest.raises(InvalidSearch, match="drug_name='pembrolizumab'"):
        apply_request_filters(plan(("x", {"query.intr": "nivolumab"})), request(drug_name="pembrolizumab"))


def test_a_narrowing_of_the_user_value_is_kept():
    p = plan(("x", {"query.cond": '"uveal melanoma"'}))
    prepared, _ = apply_request_filters(p, request(condition="Melanoma"))
    assert prepared[0][1].search["query.cond"] == '("uveal melanoma") AND "Melanoma"'


def test_containment_is_by_whole_words():
    # "melanoma" is not inside "melanomas-like" spellings of another word, and "lung" is not "lunge"
    with pytest.raises(InvalidSearch):
        apply_request_filters(plan(("x", {"query.cond": "hypermelanosis"})), request(condition="melanosis"))


def test_sponsor_field_means_the_lead_sponsor():
    # request.sponsor is documented as the lead sponsor; query.spons also matches collaborators
    prepared, _ = apply_request_filters(plan(("x", {"query.cond": "asthma"})), request(sponsor="Pfizer"))
    assert prepared[0][1].search == {"query.cond": "asthma", "query.lead": '"Pfizer"'}


def test_a_different_sponsor_in_the_plan_conflicts_with_the_sponsor_field():
    with pytest.raises(InvalidSearch, match="sponsor='Pfizer'"):
        apply_request_filters(plan(("x", {"query.spons": '"Novartis"'})), request(sponsor="Pfizer"))
    prepared, _ = apply_request_filters(plan(("x", {"query.spons": '"Pfizer"'})), request(sponsor="Pfizer"))
    assert prepared[0][1].search == {"query.spons": '"Pfizer"', "query.lead": '"Pfizer"'}


def test_filters_apply_to_every_search():
    p = plan(("A", {"query.intr": "nivolumab"}), ("B", {"query.intr": "pembrolizumab"}))
    prepared, _ = apply_request_filters(p, request(trial_phase=["PHASE3"]))
    assert {params.search["filter.advanced"] for _, params in prepared} == {"AREA[Phase](PHASE3)"}


def test_filters_summary_shows_the_exact_searches():
    prepared, _ = apply_request_filters(plan(("x", {"query.cond": "asthma"})), request())
    assert filters_summary(prepared) == {"steps": [{"label": "x", "endpoint": "studies", "params": {"query.cond": "asthma"}}]}


def test_phrase_quotes_user_values():
    assert phrase("multiple sclerosis") == '"multiple sclerosis"'
    assert phrase('say "hi"') == '"say hi"'


# --- Steps on other endpoints ----------------------------------------------------------------


def test_plan_can_mix_endpoints():
    p = SearchPlan.model_validate(
        {
            "steps": [
                {"endpoint": "studies", "label": "Asthma", "params": {"query.cond": '"asthma"'}},
                {"endpoint": "stats/field/values", "label": "All trials", "fields": ["Phase"]},
            ],
            "rationale": "Asthma trials vs the whole registry, by phase.",
        }
    )
    assert [s.endpoint for s in p.steps] == ["studies", "stats/field/values"]


def test_identical_steps_on_any_endpoint_are_rejected():
    same = {"endpoint": "stats/field/values", "fields": ["Phase"]}
    with pytest.raises(ValidationError, match="must differ"):
        SearchPlan.model_validate({"steps": [{**same, "label": "A"}, {**same, "label": "B"}], "rationale": "r"})


def test_registry_wide_step_with_user_filters_is_sent_back_to_the_planner():
    p = SearchPlan.model_validate(
        {"steps": [{"endpoint": "stats/field/values", "label": "All", "fields": ["Phase"]}], "rationale": "r"}
    )
    with pytest.raises(InvalidSearch, match="cannot apply them"):
        apply_request_filters(p, request(condition="asthma"))


def test_other_endpoints_pass_through_in_plan_order():
    p = SearchPlan.model_validate(
        {
            "steps": [
                {"endpoint": "stats/size", "label": "Sizes"},
                {"endpoint": "studies", "label": "Asthma", "params": {"query.cond": "asthma"}},
            ],
            "rationale": "r",
        }
    )
    prepared, _ = apply_request_filters(p, request())
    assert [label for label, _ in prepared] == ["Sizes", "Asthma"]
    assert filters_summary(prepared)["steps"][0] == {"label": "Sizes", "endpoint": "stats/size", "params": {}}


def test_filters_on_a_single_study_lookup_only_warn():
    p = SearchPlan.model_validate({"steps": [{"endpoint": "study", "label": "One", "nct_id": "NCT05064059"}], "rationale": "r"})
    _, warnings = apply_request_filters(p, request(condition="asthma"))
    assert "lookup of one trial" in warnings[0]
