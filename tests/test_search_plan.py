"""SearchPlan (what the planner means) and how code turns it into API calls: merging the user's
fields, resolving names to the registry's own, keeping comparison sides apart, compiling."""

import asyncio

import pytest
from pydantic import ValidationError

from exploreclinicaltrials.fetch.models import Trial
from exploreclinicaltrials.fetch.stats import FieldValuesResponse
from exploreclinicaltrials.models.request import QueryRequest
from exploreclinicaltrials.workflow import FetchResult, SearchPlan, StatsResult
from exploreclinicaltrials.workflow.errors import InvalidSearch
from exploreclinicaltrials.workflow.intent import Resolver, phrase
from exploreclinicaltrials.workflow.translate import filters_summary, prepare_plan

# --- A fake registry for name lookups ------------------------------------------------------------

COUNTRIES = ["France", "Germany", "Turkey (Türkiye)", "United States", "Japan", "South Korea"]


def indexed(n: int, drugs: list[str] = (), conditions: list[str] = (), lead: str | None = None) -> list[Trial]:
    return [
        Trial(nct_id=f"NCT{i:08d}", intervention_mesh=list(drugs), condition_mesh=list(conditions), lead_sponsor=lead)
        for i in range(n)
    ]


# How the fake registry indexes the trials that match a name (sampled by the resolver).
INDEX = {
    ("query.intr", "Ozempic"): indexed(43, drugs=["semaglutide"]) + indexed(7, drugs=["tirzepatide"]),
    ("query.intr", "Wegovy"): indexed(40, drugs=["semaglutide"]),
    ("query.intr", "semaglutide"): indexed(50, drugs=["semaglutide"]),
    ("query.intr", "Keytruda"): indexed(50, drugs=["pembrolizumab"]),
    # mostly combination trials: the partner drug is the most common index term
    ("query.intr", "nivolumab"): indexed(10, drugs=["nivolumab"]) + indexed(30, drugs=["ipilimumab"]),
    ("query.cond", "type 2 diabetes"): indexed(41, conditions=["Diabetes Mellitus, Type 2"]) + indexed(9),
    ("query.spons", "MSD"): indexed(40, lead="Merck Sharp & Dohme LLC") + indexed(7, lead="Organon"),
    # the text search for "Hodgkin lymphoma" also matches "non-Hodgkin lymphoma", so the opposite
    # disease is the most common index term among the matches
    ("query.cond", "Hodgkin lymphoma"): indexed(29, conditions=["Lymphoma, Non-Hodgkin"])
    + indexed(12, conditions=["Hodgkin Disease"])
    + indexed(9),
    ("query.cond", "small cell lung cancer"): indexed(30, conditions=["Carcinoma, Non-Small-Cell Lung"])
    + indexed(15, conditions=["Small Cell Lung Carcinoma"]),
    ("query.cond", "non-small cell lung cancer"): indexed(45, conditions=["Carcinoma, Non-Small-Cell Lung"]),
}


async def fake_search(params, limit=None, on_progress=None):
    ((param, value),) = params.search.items()
    trials = INDEX.get((param, value.strip('"')), [])
    return FetchResult(trials=trials, total_matched=len(trials))


async def fake_stats(step):
    data = FieldValuesResponse.model_validate(
        [{"field": "LocationCountry", "piece": "LocationCountry", "type": "STRING", "missingStudiesCount": 0,
          "uniqueValuesCount": len(COUNTRIES), "topValues": [{"value": c, "studiesCount": 1} for c in COUNTRIES]}]
    )  # fmt: skip
    return StatsResult(endpoint=step.endpoint, data=data)


def prepare(plan: SearchPlan, **fields):
    return asyncio.run(prepare_plan(plan, QueryRequest(query="test question", **fields), Resolver(fake_search, fake_stats)))


def plan(*steps: tuple[str, dict], rationale: str = "r", **extra) -> SearchPlan:
    return SearchPlan.model_validate(
        {"steps": [{"endpoint": "studies", "label": label, **slots} for label, slots in steps], "rationale": rationale, **extra}
    )


def searches(prepared) -> list[dict]:
    return [target.search for _, target in prepared.steps]


# --- What the planner may write ----------------------------------------------------------


def test_valid_plan():
    p = plan(("MS", {"conditions": ["multiple sclerosis"], "phases": ["PHASE2", "PHASE3"]}))
    assert p.steps[0].conditions == ["multiple sclerosis"] and not p.is_comparison


@pytest.mark.parametrize(
    "slots, error",
    [
        ({}, "at least one search slot"),
        ({"params": {"query.intr": "x"}}, "at least one search slot"),  # raw parameters are not slots
        ({"drugs": ["x"], "advanced": "AREA[StudyType]INTERVENTIONAL"}, "study_type"),
        ({"drugs": ["x"], "advanced": "AREA[StartDate]RANGE[2015-01-01,MAX]"}, "period"),
        ({"exclude_conditions": ["type 1 diabetes"]}, "need drugs / conditions"),
        ({"drugs": ["x"], "min_enrollment": 500, "max_enrollment": 100}, "at most"),
    ],
)
def test_invalid_steps_are_rejected(slots, error):
    with pytest.raises(ValidationError, match=error):
        plan(("x", slots))


def test_labels_unique_and_compared_searches_differ():
    with pytest.raises(ValidationError, match="labels must be unique"):
        plan(("Drug", {"drugs": ["a"]}), ("drug", {"drugs": ["b"]}))
    with pytest.raises(ValidationError, match="must differ"):
        plan(("A", {"drugs": ["a"]}), ("B", {"drugs": ["a"]}))


# --- Compiling slots to API parameters ---------------------------------------------------------


def test_every_slot_compiles_to_its_parameter():
    p = plan(
        (
            "x",
            {
                "drugs": ["metformin"], "conditions": ["obesity"], "sponsors": ["Novartis"], "countries": ["Japan"],
                "statuses": ["RECRUITING", "COMPLETED"], "phases": ["PHASE3"], "study_type": "interventional",
                "min_enrollment": 500, "keywords": ["CAR-T"], "advanced": "AREA[DesignAllocation]RANDOMIZED",
                "period": {"field": "start", "from_year": 2015},
            },
        )
    )  # fmt: skip
    assert searches(prepare(p)) == [
        {
            "query.intr": '"metformin"',
            "query.cond": '"obesity"',
            "query.lead": '"Novartis"',  # sponsors are LEAD sponsors
            "query.locn": '"Japan"',
            "query.term": '"CAR-T"',
            "filter.overallStatus": "RECRUITING|COMPLETED",
            "filter.advanced": "AREA[Phase](PHASE3) AND AREA[StudyType]INTERVENTIONAL AND AREA[EnrollmentCount]RANGE[500,MAX]"
            " AND (AREA[DesignAllocation]RANDOMIZED) AND AREA[StartDate]RANGE[2015-01-01,MAX]",
        }
    ]


def test_study_type_defaults_to_all_studies():
    assert "filter.advanced" not in searches(prepare(plan(("x", {"conditions": ["asthma"]}))))[0]


def test_combination_therapy_and_exclusions():
    both = prepare(plan(("x", {"drugs": ["atezolizumab", "bevacizumab"], "drugs_match": "all"})))
    assert searches(both)[0]["query.intr"] == '"atezolizumab" AND "bevacizumab"'
    excluded = prepare(plan(("x", {"conditions": ["diabetes"], "exclude_conditions": ["type 1 diabetes"]})))
    assert searches(excluded)[0]["query.cond"] == '("diabetes") NOT "type 1 diabetes"'


def test_a_region_becomes_its_countries_as_the_registry_spells_them():
    target = prepare(plan(("x", {"conditions": ["asthma"], "region": "europe"}))).steps[0][1]
    assert target.countries == ["France", "Germany", "Turkey (Türkiye)"]  # not the US, Japan or Korea
    assert target.search["query.locn"] == '"France" OR "Germany" OR "Turkey (Türkiye)"'


def test_a_typed_country_takes_the_registry_spelling():
    assert prepare(plan(("x", {"conditions": ["asthma"], "countries": ["Türkiye"]}))).steps[0][1].countries == ["Turkey (Türkiye)"]


# --- Resolving names to the registry's own -------------------------------------------------------


def test_a_brand_is_also_searched_as_the_name_its_trials_are_indexed_under():
    prepared = prepare(plan(("Ozempic", {"drugs": ["Ozempic"]})))
    assert searches(prepared)[0]["query.intr"] == '("Ozempic" OR "semaglutide")'
    assert "43 of 50 sampled trials" in prepared.notes[0]


def test_a_name_the_registry_already_indexes_is_never_expanded():
    # nivolumab is itself an index term; ipilimumab is only its most common partner drug
    assert searches(prepare(plan(("x", {"drugs": ["nivolumab"]}))))[0]["query.intr"] == '"nivolumab"'
    prepared = prepare(plan(("x", {"drugs": ["semaglutide"]})))
    assert searches(prepared)[0]["query.intr"] == '"semaglutide"' and not prepared.notes


def test_an_unknown_name_is_searched_as_written():
    assert searches(prepare(plan(("x", {"drugs": ["Ozempik"]}))))[0]["query.intr"] == '"Ozempik"'


def test_condition_spellings_and_sponsor_names_resolve():
    cond = prepare(plan(("x", {"conditions": ["type 2 diabetes"]})))
    assert searches(cond)[0]["query.cond"] == '("type 2 diabetes" OR "Diabetes Mellitus, Type 2")'
    sponsor = prepare(plan(("x", {"sponsors": ["MSD"]})))
    assert searches(sponsor)[0]["query.lead"] == '("MSD" OR "Merck Sharp & Dohme LLC")'


def test_comparison_sides_that_resolve_to_the_same_drug_stay_apart():
    prepared = prepare(plan(("Ozempic", {"drugs": ["Ozempic"]}), ("Wegovy", {"drugs": ["Wegovy"]})))
    assert [s["query.intr"] for s in searches(prepared)] == ['"Ozempic"', '"Wegovy"']
    assert "both indexed as semaglutide" in prepared.warnings[0]
    brand_vs_generic = prepare(plan(("Ozempic", {"drugs": ["Ozempic"]}), ("Semaglutide", {"drugs": ["semaglutide"]})))
    assert [s["query.intr"] for s in searches(brand_vs_generic)] == ['"Ozempic"', '"semaglutide"']


def test_different_drugs_in_a_comparison_each_resolve():
    prepared = prepare(plan(("Ozempic", {"drugs": ["Ozempic"]}), ("Keytruda", {"drugs": ["Keytruda"]})))
    assert [s["query.intr"] for s in searches(prepared)] == ['("Ozempic" OR "semaglutide")', '("Keytruda" OR "pembrolizumab")']


NOT_NHL = (
    '(AREA[ConditionMeshTerm]"Hodgkin Disease" OR (NOT AREA[ConditionMeshTerm]"Lymphoma, Non-Hodgkin" '
    'AND NOT AREA[ConditionAncestorTerm]"Lymphoma, Non-Hodgkin"))'
)


def test_a_condition_is_never_expanded_to_its_opposite():
    prepared = prepare(plan(("x", {"conditions": ["Hodgkin lymphoma"]})))
    assert searches(prepared)[0]["query.cond"] == '"Hodgkin lymphoma"'


def test_trials_indexed_only_as_the_opposite_condition_are_left_out():
    # keep trials indexed as the condition itself (mixed lymphoma trials included) and trials the
    # registry has not indexed as the opposite one; drop the rest
    prepared = prepare(plan(("x", {"conditions": ["Hodgkin lymphoma"]})))
    assert searches(prepared)[0]["filter.advanced"] == NOT_NHL
    assert any("Lymphoma, Non-Hodgkin" in n and "left out" in n for n in prepared.notes)
    sclc = prepare(plan(("x", {"conditions": ["small cell lung cancer"]})))
    assert 'NOT AREA[ConditionMeshTerm]"Carcinoma, Non-Small-Cell Lung"' in searches(sclc)[0]["filter.advanced"]
    assert 'AREA[ConditionMeshTerm]"Small Cell Lung Carcinoma"' in searches(sclc)[0]["filter.advanced"]


def test_a_name_that_is_itself_the_negated_form_resolves_normally():
    prepared = prepare(plan(("x", {"conditions": ["non-small cell lung cancer"]})))
    search = searches(prepared)[0]
    assert search["query.cond"] == '("non-small cell lung cancer" OR "Carcinoma, Non-Small-Cell Lung")'
    assert "filter.advanced" not in search


def test_the_opposite_condition_filter_applies_only_to_a_step_with_that_one_condition():
    prepared = prepare(plan(("x", {"conditions": ["Hodgkin lymphoma", "type 2 diabetes"]})))
    assert "filter.advanced" not in searches(prepared)[0]
    assert any("Lymphoma, Non-Hodgkin" in w for w in prepared.warnings)


# --- The user's structured fields win ------------------------------------------------------------


def test_no_user_filters_leaves_the_plan_as_written():
    prepared = prepare(plan(("x", {"conditions": ["asthma"]})))
    assert searches(prepared) == [{"query.cond": '"asthma"'}] and prepared.warnings == []


def test_a_field_fills_an_empty_slot():
    assert searches(prepare(plan(("x", {"drugs": ["pembrolizumab"]})), condition="melanoma"))[0] == {
        "query.intr": '"pembrolizumab"',
        "query.cond": '"melanoma"',
    }


def test_a_conflicting_field_replaces_the_question_term_and_says_so():
    # r22: "lung cancer trials by phase" with condition=melanoma charted the few trials mentioning both
    prepared = prepare(plan(("x", {"conditions": ["lung cancer"]})), condition="melanoma")
    assert searches(prepared)[0]["query.cond"] == '"melanoma"'
    assert "lung cancer replaced by the user's condition='melanoma'" in prepared.notes[0]


def test_a_narrowing_of_the_field_is_kept_and_a_widening_is_trimmed():
    narrow = prepare(plan(("x", {"conditions": ["uveal melanoma"]})), condition="melanoma")
    assert searches(narrow)[0]["query.cond"] == '"uveal melanoma"'
    trimmed = prepare(plan(("x", {"drugs": ["pembrolizumab", "nivolumab"]})), drug_name="Pembrolizumab")
    assert searches(trimmed)[0]["query.intr"] == '"pembrolizumab"'
    assert "nivolumab dropped" in trimmed.notes[0]


def test_sponsor_field_is_the_lead_sponsor():
    assert searches(prepare(plan(("x", {"conditions": ["asthma"]})), sponsor="Pfizer"))[0]["query.lead"] == '"Pfizer"'


def test_phases_statuses_and_years_from_the_user_apply():
    p = plan(("x", {"conditions": ["asthma"], "phases": ["PHASE2"], "period": {"field": "start", "from_year": 2010}}))
    s = searches(prepare(p, trial_phase=["PHASE3"], recruitment_status=["RECRUITING"], start_year=2015))[0]
    assert s["filter.overallStatus"] == "RECRUITING"
    assert s["filter.advanced"] == "AREA[Phase](PHASE3) AND AREA[StartDate]RANGE[2015-01-01,MAX]"


def test_comparison_may_skip_the_field_only_when_it_is_a_compared_side():
    two = plan(("Nivolumab", {"drugs": ["nivolumab"]}), ("Pembrolizumab", {"drugs": ["pembrolizumab"]}))
    prepared = prepare(two, drug_name="Pembrolizumab")
    assert [s["query.intr"] for s in searches(prepared)] == ['"nivolumab"', '"pembrolizumab"']
    assert "Ignored drug_name" in prepared.warnings[0]
    with pytest.raises(InvalidSearch, match="drug_name='Relatlimab'"):
        prepare(two, drug_name="Relatlimab")


def test_filters_apply_to_every_side():
    two = plan(("A", {"drugs": ["nivolumab"]}), ("B", {"drugs": ["pembrolizumab"]}))
    assert {s["filter.advanced"] for s in searches(prepare(two, trial_phase=["PHASE3"]))} == {"AREA[Phase](PHASE3)"}


# --- Summaries and other endpoints ----------------------------------------------------------------


def test_filters_summary_shows_the_exact_searches_and_the_intent():
    prepared = prepare(plan(("Ozempic", {"drugs": ["Ozempic"]})))
    assert filters_summary(prepared.steps) == {
        "steps": [
            {
                "label": "Ozempic",
                "endpoint": "studies",
                "params": {"query.intr": '("Ozempic" OR "semaglutide")'},
                "intent": {"drugs": ["Ozempic"]},
                "searched_as": {"drugs:Ozempic": ["Ozempic", "semaglutide"]},
            }
        ]
    }


def test_descriptions_say_what_was_searched_in_plain_words():
    prepared = prepare(plan(("Ozempic", {"drugs": ["Ozempic"], "phases": ["PHASE3"]})), start_year=2018)
    assert prepared.descriptions == ["Ozempic: all study types testing Ozempic or semaglutide; in PHASE3; started 2018–now."]


def test_phrase_quotes_values():
    assert phrase("multiple sclerosis") == '"multiple sclerosis"'
    assert phrase('say "hi"') == '"say hi"'


def test_plan_can_mix_endpoints_and_keeps_their_order():
    p = SearchPlan.model_validate(
        {"steps": [{"endpoint": "stats/size", "label": "Sizes"}, {"endpoint": "studies", "label": "Asthma", "conditions": ["asthma"]}],
         "rationale": "r"}
    )  # fmt: skip
    prepared = prepare(p)
    assert [label for label, _ in prepared.steps] == ["Sizes", "Asthma"]
    assert filters_summary(prepared.steps)["steps"][0] == {"label": "Sizes", "endpoint": "stats/size", "params": {}}


def test_identical_steps_on_any_endpoint_are_rejected():
    same = {"endpoint": "stats/field/values", "fields": ["Phase"]}
    with pytest.raises(ValidationError, match="must differ"):
        SearchPlan.model_validate({"steps": [{**same, "label": "A"}, {**same, "label": "B"}], "rationale": "r"})


def test_registry_wide_step_with_user_filters_is_sent_back_to_the_planner():
    p = SearchPlan.model_validate({"steps": [{"endpoint": "stats/field/values", "label": "All", "fields": ["Phase"]}], "rationale": "r"})
    with pytest.raises(InvalidSearch, match="cannot apply them"):
        prepare(p, condition="asthma")


def test_filters_on_a_single_study_lookup_only_warn():
    p = SearchPlan.model_validate({"steps": [{"endpoint": "study", "label": "One", "nct_id": "NCT05064059"}], "rationale": "r"})
    assert "lookup of one trial" in prepare(p, condition="asthma").warnings[0]


def test_a_drugs_used_together_network_refuses_an_intervention_count_filter():
    """The filter cannot change the pairs, only each drug's count: allowing it makes the same question
    give different numbers depending on the planner's choice."""
    combos = ("Myeloma", {"conditions": ["multiple myeloma"], "advanced": "AREA[NumInterventions]RANGE[2,MAX]"})
    with pytest.raises(ValidationError, match="remove the NumInterventions filter"):
        plan(combos, breakdown="intervention x intervention")
    with pytest.raises(ValidationError, match="NumInterventions"):
        plan(combos, breakdown=" Intervention X intervention ".replace("X", "x"))
    plan(("Myeloma", {"conditions": ["multiple myeloma"]}), breakdown="intervention x intervention")
    plan(combos, breakdown="lead_sponsor x intervention")  # other networks: the question decides
    plan(combos, breakdown="phase")  # e.g. "phases of combination trials"
