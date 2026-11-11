"""Endpoint step models: validation, and that their rules match the stored OpenAPI spec."""

from pathlib import Path

import pytest
import yaml
from pydantic import TypeAdapter, ValidationError

from trialsight.fetch.endpoints import (
    FIELD_NAME_PATTERN,
    NCT_ID_PATTERN,
    FieldStatsType,
    FieldValuesStep,
    PlanStep,
    StudiesStep,
    StudyStep,
)

SPEC = yaml.safe_load((Path(__file__).resolve().parent.parent / "docs" / "ctgov" / "openapi.yaml").read_text())
STEP = TypeAdapter(PlanStep)


def spec_params(path: str) -> dict[str, dict]:
    return {p["name"]: p for p in SPEC["paths"][path]["get"].get("parameters", [])}


# --- In sync with the spec ---------------------------------------------------------------------


def test_every_step_calls_a_real_endpoint():
    steps = [
        StudiesStep(label="x", conditions=["asthma"]),
        StudyStep(label="x", nct_id="NCT05064059"),
        FieldValuesStep(label="x", fields=["Phase"]),
        STEP.validate_python({"endpoint": "stats/field/sizes", "label": "x", "fields": ["Condition"]}),
        STEP.validate_python({"endpoint": "stats/size", "label": "x"}),
    ]
    for step in steps:
        template = "/studies/{nctId}" if isinstance(step, StudyStep) else step.path()
        assert template in SPEC["paths"], template


def test_query_params_exist_on_their_endpoint():
    values = FieldValuesStep(label="x", fields=["Phase", "OverallStatus"], types=["ENUM"])
    assert set(values.query_params()) <= set(spec_params("/stats/field/values"))
    sizes = STEP.validate_python({"endpoint": "stats/field/sizes", "label": "x", "fields": ["Condition"]})
    assert set(sizes.query_params()) <= set(spec_params("/stats/field/sizes"))


def test_patterns_and_enums_match_the_spec():
    assert spec_params("/stats/field/values")["fields"]["schema"]["items"]["pattern"] == FIELD_NAME_PATTERN
    assert spec_params("/stats/field/sizes")["fields"]["schema"]["items"]["pattern"] == FIELD_NAME_PATTERN
    assert spec_params("/studies/{nctId}")["nctId"]["schema"]["pattern"] == NCT_ID_PATTERN
    assert [t.value for t in FieldStatsType] == SPEC["components"]["schemas"]["FieldStatsType"]["enum"]


# --- Validation ----------------------------------------------------------------------------------


def test_steps_are_chosen_by_endpoint():
    step = STEP.validate_python({"endpoint": "stats/field/values", "label": "All trials", "fields": ["Phase"]})
    assert isinstance(step, FieldValuesStep)
    assert step.query_params() == {"fields": "Phase"}


@pytest.mark.parametrize(
    "raw",
    [
        {"endpoint": "stats/everything", "label": "x"},  # no such endpoint
        {"endpoint": "studies", "label": "x", "params": {"query.intr": "x"}},  # raw parameters: slots only
        {"endpoint": "studies", "label": "x", "drugs": ["x"], "advanced": "AREA[Phase]PHASE3"},  # phases has a slot
        {"endpoint": "studies", "label": "x", "exclude_conditions": ["type 1 diabetes"]},  # nothing to exclude from
        {"endpoint": "study", "label": "x", "nct_id": "12345"},  # not an NCT number
        {"endpoint": "stats/field/values", "label": "x", "fields": []},  # needs a field
        {"endpoint": "stats/field/values", "label": "x", "fields": ["Phase; DROP"]},  # breaks the spec pattern
        {"endpoint": "stats/field/values", "label": "x", "fields": ["Phase"], "types": ["TEXT"]},  # unknown type
    ],
)
def test_invalid_steps_are_rejected(raw):
    with pytest.raises(ValidationError):
        STEP.validate_python(raw)


def test_nct_id_is_normalised_in_the_path():
    assert StudyStep(label="x", nct_id="nct05064059").path() == "/studies/NCT05064059"
