"""ClinicalTrials.gov API models, tested against a real saved response.

Fixture: GET /api/v2/studies?query.intr=pembrolizumab
         &filter.advanced=AREA[Phase]PHASE3 AND AREA[StartDate]RANGE[2015-01-01,MAX]
         &fields=<DEFAULT_FIELDS>&pageSize=2&countTotal=true   (fetched 2026-11-07)
"""

import json
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from cheiron.fetch import StudiesPage, StudySearchParams, Trial, build_advanced_filter
from cheiron.fetch.models import RawStudy, date_range
from cheiron.models import TrialPhase

FIXTURE = Path(__file__).parent / "fixtures" / "ctgov" / "pembrolizumab_phase3_page1.json"


def load_page() -> StudiesPage:
    return StudiesPage.model_validate(json.loads(FIXTURE.read_text()))


# --- Request -----------------------------------------------------------------------


def test_phase_filter_and_date_ranges():
    assert build_advanced_filter([TrialPhase.PHASE2, TrialPhase.PHASE3]) == "AREA[Phase](PHASE2 OR PHASE3)"
    assert build_advanced_filter() is None
    assert date_range("start", 2015, None) == "AREA[StartDate]RANGE[2015-01-01,MAX]"
    assert date_range("completion", None, 2020) == "AREA[CompletionDate]RANGE[MIN,2020-12-31]"


def test_search_params_become_api_query_string():
    params = StudySearchParams(
        search={
            "query.intr": ' "pembrolizumab" ',
            "filter.overallStatus": "RECRUITING|COMPLETED",
            "filter.advanced": build_advanced_filter([TrialPhase.PHASE3]),
        },
        fields=["NCTId", "Phase"],
        page_size=50,
    ).to_query_params()
    assert params == {
        "query.intr": '"pembrolizumab"',  # trimmed
        "filter.overallStatus": "RECRUITING|COMPLETED",
        "filter.advanced": "AREA[Phase](PHASE3)",
        "fields": "NCTId|Phase",
        "pageSize": "50",
        "countTotal": "true",
    }


def test_count_total_is_dropped_after_first_page():
    params = StudySearchParams(search={"query.cond": "asthma"}, page_token="abc").to_query_params()
    assert params["pageToken"] == "abc"
    assert "countTotal" not in params


@pytest.mark.parametrize(
    ("search", "error"),
    [
        ({"query.drug": "x"}, "unknown or reserved"),  # not an API parameter
        ({"pageSize": "5"}, "unknown or reserved"),  # paging belongs to code
        ({"query.cond": "  "}, "empty value"),
        ({"filter.overallStatus": "RECRUITING|OPEN"}, "invalid status"),
    ],
)
def test_bad_search_params_are_rejected(search, error):
    with pytest.raises(ValidationError, match=error):
        StudySearchParams(search=search)


# --- Response ----------------------------------------------------------------------


def test_real_page_parses():
    page = load_page()
    assert page.total_count == 364
    assert page.next_page_token
    assert len(page.studies) == 2


def test_real_study_normalizes_to_trial():
    trial = Trial.from_raw(load_page().studies[0])
    assert trial.nct_id == "NCT05064059"
    assert trial.overall_status == "COMPLETED"
    assert trial.start_date == date(2021, 11, 10)
    assert trial.start_year == 2021
    assert trial.phases == ["PHASE3"]
    assert trial.lead_sponsor == "Merck Sharp & Dohme LLC"
    assert trial.sponsor_class == "INDUSTRY"
    assert trial.conditions == ["Colorectal Cancer"]
    assert [i.name for i in trial.interventions] == ["favezelimab/pembrolizumab", "regorafenib", "TAS-102"]
    assert trial.enrollment == 441


def test_countries_are_deduplicated_in_order():
    trial = Trial.from_raw(load_page().studies[0])
    assert len(trial.countries) == len(set(trial.countries))
    assert trial.countries[0] == "United States"  # first site listed


def test_sparse_record_does_not_crash():
    """Real records often omit whole modules; only the NCT id is guaranteed."""
    raw = StudiesPage.model_validate(
        {"studies": [{"protocolSection": {"identificationModule": {"nctId": "NCT00000001"}}}]}
    ).studies[0]
    trial = Trial.from_raw(raw)
    assert trial.start_date is None
    assert trial.phases == [] and trial.countries == [] and trial.interventions == []


def test_partial_start_date_becomes_first_of_month():
    raw = StudiesPage.model_validate(
        {
            "studies": [
                {
                    "protocolSection": {
                        "identificationModule": {"nctId": "NCT00000002"},
                        "statusModule": {"startDateStruct": {"date": "2015-03"}},
                    }
                }
            ]
        }
    ).studies[0]
    assert Trial.from_raw(raw).start_date == date(2015, 3, 1)


def test_mesh_terms_are_kept_from_the_derived_section():
    raw = RawStudy.model_validate(
        {
            "protocolSection": {"identificationModule": {"nctId": "NCT04639414"}},
            "derivedSection": {
                "conditionBrowseModule": {"meshes": [{"term": "Diabetes Mellitus, Type 2"}]},
                "interventionBrowseModule": {"meshes": [{"term": "semaglutide"}, {"term": "semaglutide"}]},
            },
        }
    )
    trial = Trial.from_raw(raw)
    assert trial.condition_mesh == ["Diabetes Mellitus, Type 2"]
    assert trial.intervention_mesh == ["semaglutide"]  # distinct
    assert Trial.from_raw(RawStudy.model_validate({"protocolSection": {"identificationModule": {"nctId": "NCT00000001"}}})).intervention_mesh == []
