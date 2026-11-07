"""The data profile the agent sees instead of records."""

import json
from datetime import date
from pathlib import Path

from cheiron.fetch.models import StudiesPage, Trial
from cheiron.fetch.stats import FieldValuesResponse, incomplete_fields
from cheiron.workflow.plans import Dimension, StatsResult
from cheiron.workflow.profile import TOP_VALUES, build_profile

FIXTURES = Path(__file__).parent / "fixtures" / "ctgov"


def real_trials() -> list[Trial]:
    page = StudiesPage.model_validate(json.loads((FIXTURES / "pembrolizumab_phase3_page1.json").read_text()))
    return [Trial.from_raw(s) for s in page.studies]


def trial(n: int, **fields) -> Trial:
    return Trial(nct_id=f"NCT{n:08d}", **fields)


def test_every_field_is_profiled_from_real_trials():
    profile = build_profile({"Pembrolizumab": real_trials()}, total_matched=364)

    assert set(profile.fields) == set(Dimension) - {Dimension.GROUP}
    assert profile.trials_fetched == 2 and profile.total_matched == 364
    assert profile.fields[Dimension.PHASE].top_values == [("PHASE3", 2)]
    assert dict(profile.fields[Dimension.SPONSOR].top_values) == {"Merck Sharp & Dohme LLC": 1, "Regeneron Pharmaceuticals": 1}
    assert profile.fields[Dimension.ENROLLMENT].numeric.max == 1546
    assert profile.fields[Dimension.COUNTRY].multi_valued


def test_multi_valued_trials_count_once_per_value_and_missing_is_counted():
    trials = [
        trial(1, phases=["PHASE1", "PHASE2"], start_date=date(2020, 1, 1)),
        trial(2, phases=["PHASE2"]),
        trial(3),  # no phase, no start date
    ]
    p = build_profile({"All": trials}, total_matched=3)
    assert dict(p.fields[Dimension.PHASE].top_values) == {"PHASE2": 2, "PHASE1": 1}  # sums to 3 for 2 trials
    assert p.fields[Dimension.PHASE].missing == 1
    assert p.fields[Dimension.START_YEAR].top_values == [("2020", 1)] and p.fields[Dimension.START_YEAR].missing == 2


def test_comparison_reports_missing_per_side():
    p = build_profile({"A": [trial(1, phases=["PHASE3"])], "B": [trial(2), trial(3)]}, total_matched=3)
    assert p.group_sizes == {"A": 1, "B": 2}
    assert p.fields[Dimension.PHASE].missing_by_group == {"A": 0, "B": 2}


def test_top_values_are_capped_so_the_profile_stays_small():
    trials = [trial(i, lead_sponsor=f"Sponsor {i}", countries=[f"C{i}", f"D{i}"]) for i in range(500)]
    p = build_profile({"All": trials}, total_matched=500)
    sponsor = p.fields[Dimension.SPONSOR]
    assert sponsor.distinct == 500 and len(sponsor.top_values) == TOP_VALUES
    assert len(p.model_dump_json()) < 6000  # ~1.5k tokens even for 500 distinct sponsors and 1,000 countries


def test_registry_stats_are_summarised_with_incomplete_fields_flagged():
    data = FieldValuesResponse.model_validate(json.loads((FIXTURES / "stats_field_values.json").read_text()))
    result = StatsResult(endpoint="stats/field/values", data=data, incomplete_fields=incomplete_fields(data))
    p = build_profile({}, total_matched=0, stats=[("All trials", result)])

    assert p.fields == {}  # no trials fetched, so no trial fields
    by_piece = {f.piece: f for f in p.stats[0].fields}
    assert by_piece["Phase"].distinct == 6 and not by_piece["Phase"].incomplete
    assert by_piece["LeadSponsorName"].incomplete and len(by_piece["LeadSponsorName"].top_values) == TOP_VALUES
    assert by_piece["StartDate"].min and by_piece["EnrollmentCount"].avg


def test_profile_never_contains_records():
    p = build_profile({"Pembrolizumab": real_trials()}, total_matched=364)
    text = p.model_dump_json()
    assert "NCT05064059" not in text  # no trial ids
    assert "Favezelimab" not in text.lower().replace("favezelimab/pembrolizumab", "")  # no titles
