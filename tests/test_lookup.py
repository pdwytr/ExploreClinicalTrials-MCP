"""find_trials and get_trial: the search they send and what the model reads back.
Fixtures are real ClinicalTrials.gov responses (tests/fixtures/ctgov)."""

import json
from pathlib import Path

import pytest

from exploreclinicaltrials.mcp_server import lookup
from exploreclinicaltrials.models.request import RecruitmentStatus, TrialPhase

FIXTURES = Path(__file__).parent / "fixtures" / "ctgov"
FULL = json.loads((FIXTURES / "full_NCT05064059.json").read_text())
FOUND = json.loads((FIXTURES / "find_melanoma_texas.json").read_text())


# --- The search find_trials sends ----------------------------------------------------------


def test_find_params_maps_each_filter_to_its_api_parameter():
    params = lookup.find_params(
        condition="melanoma",
        intervention="pembrolizumab",
        terms="first-line",
        sponsor="Merck",
        location="Houston, Texas",
        recruitment_status=[
            RecruitmentStatus.RECRUITING,
            RecruitmentStatus.NOT_YET_RECRUITING,
        ],
        limit=20,
    )
    assert params["query.cond"] == "melanoma"
    assert params["query.intr"] == "pembrolizumab"
    assert params["query.term"] == "first-line"
    assert params["query.spons"] == "Merck"
    assert params["query.locn"] == "Houston, Texas"
    assert params["filter.overallStatus"] == "RECRUITING,NOT_YET_RECRUITING"
    assert params["pageSize"] == "20" and params["countTotal"] == "true"
    assert "NCTId" in params["fields"] and "LocationStatus" in params["fields"]
    assert "filter.advanced" not in params


def test_an_age_keeps_trials_that_set_no_age_limit():
    """RANGE never matches a missing value: without MISSING, a 60-year-old would lose most trials
    (live, recruiting melanoma: 63 with the strict form against 462)."""
    advanced = lookup.find_params(condition="melanoma", age=60)["filter.advanced"]
    assert advanced == (
        "(AREA[MinimumAge]RANGE[MIN, 60 years] OR AREA[MinimumAge]MISSING)"
        " AND (AREA[MaximumAge]RANGE[60 years, MAX] OR AREA[MaximumAge]MISSING)"
    )


def test_sex_phase_and_age_combine_in_one_advanced_filter():
    advanced = lookup.find_params(
        condition="asthma", sex="female", trial_phase=[TrialPhase.PHASE3], age=40
    )["filter.advanced"]
    parts = advanced.split(" AND ")
    assert "AREA[Phase](PHASE3)" in parts
    assert "AREA[Sex](FEMALE OR ALL)" in parts  # trials open to everyone include her
    assert advanced.count("MISSING") == 2


def test_find_params_needs_something_to_search_and_checks_its_inputs():
    with pytest.raises(ValueError, match="at least one"):
        lookup.find_params(recruitment_status=[RecruitmentStatus.RECRUITING])
    with pytest.raises(ValueError, match="sex"):
        lookup.find_params(condition="asthma", sex="other")
    with pytest.raises(ValueError, match="age"):
        lookup.find_params(condition="asthma", age=200)
    with pytest.raises(ValueError, match="limit"):
        lookup.find_params(condition="asthma", limit=500)
    assert (
        lookup.find_params(condition="asthma", page_token="abc")["pageToken"] == "abc"
    )


# --- What find_trials returns --------------------------------------------------------------


def test_found_trials_report_the_true_total_and_one_row_per_trial():
    out = lookup.found(FOUND, location="Texas", limit=3)
    assert out["total_matched"] == FOUND["totalCount"] == 693
    assert out["shown"] == 3 and out["next_page_token"] == FOUND["nextPageToken"]
    first = out["trials"][0]
    assert first["nct_id"] == "NCT01307267"
    assert first["url"] == "https://clinicaltrials.gov/study/NCT01307267"
    assert first["interventions"] == [
        "PF-05082566",
        "rituximab",
    ]  # the record lists one twice
    assert first["sites_total"] == 42
    assert {s["city"] for s in first["matching_sites"]} <= {"Houston", "San Antonio"}
    assert all(s["state"] == "Texas" for s in first["matching_sites"])
    assert first["ages"] == "18 Years and older"


def test_matching_sites_need_every_part_of_the_location():
    sites = [
        {
            "facility": "A",
            "city": "Portland",
            "state": "Maine",
            "country": "United States",
        },
        {
            "facility": "B",
            "city": "Portland",
            "state": "Oregon",
            "country": "United States",
        },
    ]
    assert [s["facility"] for s in lookup.matching_sites(sites, "Portland, Maine")] == [
        "A"
    ]
    assert lookup.matching_sites(sites, None) == []


def test_recruiting_sites_come_first():
    sites = [
        {
            "facility": "Closed",
            "city": "Dallas",
            "state": "Texas",
            "status": "COMPLETED",
        },
        {
            "facility": "Open",
            "city": "Dallas",
            "state": "Texas",
            "status": "RECRUITING",
        },
    ]
    assert lookup.matching_sites(sites, "Texas")[0]["facility"] == "Open"


# --- What get_trial returns ----------------------------------------------------------------


def test_trial_detail_carries_what_a_reader_needs():
    out = lookup.trial_detail(FULL)
    assert out["nct_id"] == "NCT05064059"
    assert out["url"] == "https://clinicaltrials.gov/study/NCT05064059"
    assert out["status"] == "COMPLETED"
    assert out["sponsor"]["name"]
    assert out["phases"]
    assert out["arms"] and out["arms"][0]["interventions"]
    assert out["primary_outcomes"][0]["measure"] == "Overall Survival (OS)"
    assert out["eligibility"]["minimum_age"] and out["eligibility"][
        "criteria"
    ].startswith("Inclusion Criteria")
    assert out["locations"]["total"] == 152
    assert out["locations"]["by_country"]["United States"] > 0
    assert len(out["locations"]["sites"]) == lookup.MAX_SITES


def test_trial_detail_never_reports_results_only_that_they_exist():
    out = lookup.trial_detail(FULL)
    assert out["has_results"] is True
    assert "efficacy" in out["results_note"]
    assert "resultsSection" not in json.dumps(out)


def test_long_text_is_cut_and_says_so():
    record = json.loads(json.dumps(FULL))
    record["protocolSection"]["eligibilityModule"]["eligibilityCriteria"] = "x" * (
        lookup.MAX_CRITERIA + 50
    )
    criteria = lookup.trial_detail(record)["eligibility"]["criteria"]
    assert len(criteria) < lookup.MAX_CRITERIA + 100
    assert criteria.endswith(lookup.CUT)


def test_sites_can_be_narrowed_to_a_place():
    out = lookup.trial_detail(FULL, location="Kentucky")
    sites = out["locations"]["sites"]
    assert sites and all(s["state"] == "Kentucky" for s in sites)
    assert out["locations"]["matching"] == len(sites)


@pytest.mark.parametrize(
    "raw, expected", [(" nct05064059 ", "NCT05064059"), ("NCT05064059", "NCT05064059")]
)
def test_nct_ids_are_normalised(raw, expected):
    assert lookup.nct_id(raw) == expected


@pytest.mark.parametrize("raw", ["", "NCT123", "05064059", "NCT05064059; DROP"])
def test_bad_nct_ids_are_refused(raw):
    with pytest.raises(ValueError, match="NCT"):
        lookup.nct_id(raw)
