import pytest
from pydantic import ValidationError
from request_cases import INVALID_CASES, VALID_CASES

from trialsight.models import Intent, QueryRequest


@pytest.mark.parametrize("case", VALID_CASES, ids=lambda c: c.name)
def test_valid_request_is_accepted(case):
    req = QueryRequest.model_validate(case.request)
    expected_filters = {k: v for k, v in case.request.items() if k != "query"}
    assert req.filters() == expected_filters


def test_cases_cover_every_intent():
    assert {c.intent for c in VALID_CASES} == {i.value for i in Intent}


@pytest.mark.parametrize(("name", "request_body", "bad_field"), INVALID_CASES, ids=[c[0] for c in INVALID_CASES])
def test_invalid_request_is_rejected(name, request_body, bad_field):
    with pytest.raises(ValidationError) as exc:
        QueryRequest.model_validate(request_body)
    if bad_field is not None:
        error_fields = {err["loc"][0] for err in exc.value.errors() if err["loc"]}
        assert bad_field in error_fields


def test_whitespace_around_values_is_trimmed():
    req = QueryRequest.model_validate({"query": "  trials by phase  ", "drug_name": " Pembrolizumab "})
    assert req.query == "trials by phase"
    assert req.drug_name == "Pembrolizumab"
