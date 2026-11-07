"""SearchPlan: the contract between the search planner and everything after it.

Each test pins one design rule; the live-API facts behind them are noted inline.
"""

import pytest
from pydantic import TypeAdapter, ValidationError

from cheiron.workflow import SearchGroup, SearchPlan, SearchPlannerOutput, Unanswerable
from cheiron.workflow.translate import describe, filters_summary, search_params_for


def plan(**kwargs) -> SearchPlan:
    return SearchPlan.model_validate(kwargs)


# --- What a valid plan looks like ---------------------------------------------------------


def test_terms_are_trimmed_and_deduplicated_case_insensitively():
    p = plan(groups=[{"label": "Asthma", "conditions": [" asthma ", "Asthma", "COPD"]}])
    assert p.groups[0].conditions == ["asthma", "COPD"]


def test_plan_must_narrow_the_registry():
    # No terms and no filters = all 610k+ trials.
    with pytest.raises(ValidationError, match="at least one term or filter"):
        plan(groups=[{"label": "All"}])
    plan(groups=[{"label": "All"}], phases=["PHASE3"], start_year=2020)  # filters alone are enough


def test_compared_groups_need_terms_and_must_differ():
    with pytest.raises(ValidationError, match="needs at least one search term"):
        plan(groups=[{"label": "A", "interventions": ["nivolumab"]}, {"label": "B"}])
    with pytest.raises(ValidationError, match="must search for different terms"):
        plan(groups=[{"label": "A", "interventions": ["Nivolumab"]}, {"label": "B", "interventions": ["nivolumab"]}])


def test_group_labels_must_be_unique():
    with pytest.raises(ValidationError, match="labels must be unique"):
        plan(groups=[{"label": "Drug", "interventions": ["a"]}, {"label": "drug", "interventions": ["b"]}])


def test_year_range_must_be_ordered():
    with pytest.raises(ValidationError, match="start_year"):
        plan(groups=[{"label": "x", "conditions": ["asthma"]}], start_year=2020, end_year=2010)


def test_limits():
    with pytest.raises(ValidationError):
        plan(groups=[{"label": str(i), "conditions": [f"c{i}"]} for i in range(5)])  # max 4 groups
    with pytest.raises(ValidationError):
        plan(groups=[{"label": "x", "conditions": [f"c{i}" for i in range(11)]}])  # max 10 terms
    with pytest.raises(ValidationError):
        plan(groups=[{"label": "x", "conditions": ["asthma"]}], phases=[])  # empty filter list: use null


def test_unknown_filter_values_are_rejected():
    with pytest.raises(ValidationError):
        plan(groups=[{"label": "x", "conditions": ["asthma"]}], sponsor_classes=["UNIVERSITY"])


# --- Planner output: a plan or a reason ---------------------------------------------------


def test_planner_output_is_a_plan_or_unanswerable():
    adapter = TypeAdapter(SearchPlannerOutput)
    decided = adapter.validate_python({"kind": "search", "plan": {"groups": [{"label": "x", "conditions": ["asthma"]}]}})
    assert decided.plan.groups[0].conditions == ["asthma"]
    refused = adapter.validate_python({"kind": "unanswerable", "reason": "Efficacy is not in trial registry records."})
    assert isinstance(refused, Unanswerable)


# --- Translation to the API ------------------------------------------------------------------


def test_lists_become_quoted_or_expressions():
    # Live check: "asthma" 5,312 + "COPD" 5,594 -> "asthma" OR "COPD" 10,390.
    p = plan(groups=[{"label": "Airways", "conditions": ["asthma", "COPD"], "locations": ["France", "Germany"]}])
    params = search_params_for(p, p.groups[0])
    assert params.condition == '"asthma" OR "COPD"'
    assert params.location == '"France" OR "Germany"'
    assert params.intervention is None


def test_fixed_filters_become_one_advanced_expression():
    p = plan(
        groups=[{"label": "x", "conditions": ["asthma"]}],
        phases=["PHASE2", "PHASE3"],
        study_types=["INTERVENTIONAL"],
        intervention_types=["DEVICE"],
        sponsor_classes=["INDUSTRY"],
        age_groups=["CHILD"],
        start_year=2015,
    )
    assert search_params_for(p, p.groups[0]).advanced == (
        "AREA[Phase](PHASE2 OR PHASE3) AND AREA[StudyType](INTERVENTIONAL) AND "
        "AREA[InterventionType](DEVICE) AND AREA[LeadSponsorClass](INDUSTRY) AND "
        "AREA[StdAge](CHILD) AND AREA[StartDate]RANGE[2015-01-01,MAX]"
    )


def test_filters_apply_to_every_group():
    p = plan(
        groups=[{"label": "A", "interventions": ["nivolumab"]}, {"label": "B", "interventions": ["pembrolizumab"]}],
        phases=["PHASE3"],
    )
    assert {search_params_for(p, g).advanced for g in p.groups} == {"AREA[Phase](PHASE3)"}


# --- Describing the search ---------------------------------------------------------------------


def test_description_is_built_from_the_plan():
    p = plan(
        groups=[{"label": "x", "interventions": ["pembrolizumab"], "conditions": ["melanoma"]}],
        phases=["PHASE3"],
        statuses=["RECRUITING"],
        start_year=2015,
    )
    assert describe(p) == "Trials testing pembrolizumab for melanoma (phase 3, recruiting, starting 2015 or later)."


def test_comparison_description_names_each_side():
    p = SearchPlan(
        groups=[SearchGroup(label="Asthma", conditions=["asthma"]), SearchGroup(label="COPD", conditions=["COPD"])],
        sponsor_classes=["INDUSTRY"],
    )
    assert describe(p) == "Comparing Asthma: trials for asthma; COPD: trials for COPD (industry lead sponsor)."


def test_filters_summary_leaves_out_empty_values():
    p = plan(groups=[{"label": "x", "conditions": ["asthma"]}], phases=["PHASE3"])
    assert filters_summary(p) == {"phases": ["PHASE3"], "groups": [{"conditions": ["asthma"], "label": "x"}]}
