"""Registry-wide /stats and single-study steps: response models against real API samples, and the client.

Fixtures (fetched 2026-11-07):
  stats_field_values.json  GET /stats/field/values?fields=Phase|LeadSponsorName|StartDate|EnrollmentCount
  stats_field_sizes.json   GET /stats/field/sizes?fields=Condition
  stats_size.json          GET /stats/size
  study_NCT05064059.json   GET /studies/NCT05064059?fields=<DEFAULT_FIELDS>
"""

import asyncio
import json
from pathlib import Path

import httpx
import pytest
import yaml

from exploreclinicaltrials.fetch.client import CtgovClient
from exploreclinicaltrials.fetch.endpoints import FieldSizesStep, FieldValuesStep, RecordSizeStep, StudyStep
from exploreclinicaltrials.fetch.stats import (
    DateStats,
    EnumStats,
    FieldSizesResponse,
    FieldValuesResponse,
    IntegerStats,
    RecordSizesResponse,
    StringStats,
    incomplete_fields,
)
from exploreclinicaltrials.workflow.errors import InvalidSearch, UpstreamError

FIXTURES = Path(__file__).parent / "fixtures" / "ctgov"
SPEC = yaml.safe_load((Path(__file__).resolve().parent.parent / "docs" / "ctgov" / "openapi.yaml").read_text())


def fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


# --- Response models vs real responses and the spec ---------------------------------------------


def test_field_values_parse_by_type():
    stats = FieldValuesResponse.model_validate(fixture("stats_field_values.json")).root
    by_piece = {s.piece: s for s in stats}
    assert isinstance(by_piece["Phase"], EnumStats) and len(by_piece["Phase"].top_values) == 6
    assert isinstance(by_piece["LeadSponsorName"], StringStats)
    assert isinstance(by_piece["StartDate"], DateStats) and by_piece["StartDate"].min
    assert isinstance(by_piece["EnrollmentCount"], IntegerStats) and by_piece["EnrollmentCount"].avg


def test_capped_string_counts_are_flagged_and_complete_enums_are_not():
    response = FieldValuesResponse.model_validate(fixture("stats_field_values.json"))
    assert incomplete_fields(response) == ["LeadSponsorName"]  # 250 of ~52,731 sponsors returned


def test_field_sizes_and_record_sizes_parse():
    sizes = FieldSizesResponse.model_validate(fixture("stats_field_sizes.json")).root
    assert sizes[0].piece == "Condition" and sizes[0].top_sizes[0].size == 1
    records = RecordSizesResponse.model_validate(fixture("stats_size.json"))
    assert records.total_studies > 0 and records.largest_studies


@pytest.mark.parametrize(
    ("schema", "model"),
    [
        ("EnumStats", EnumStats),
        ("StringStats", StringStats),
        ("DateStats", DateStats),
        ("IntegerStats", IntegerStats),
        ("RecordSizes", RecordSizesResponse),
    ],
)
def test_models_cover_every_field_the_spec_defines(schema, model):
    spec_schema = SPEC["components"]["schemas"]["GzipStats" if schema == "RecordSizes" else schema]
    aliases = {f.alias or name for name, f in model.model_fields.items()}
    assert set(spec_schema["properties"]) <= aliases


# --- Client ------------------------------------------------------------------------------------------


def client_for(responses: dict[str, httpx.Response]) -> CtgovClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return responses.get(request.url.path.removeprefix("/api/v2"), httpx.Response(404))

    return CtgovClient(transport=httpx.MockTransport(handler), backoff_seconds=0)


async def call(client: CtgovClient, method: str, step):
    async with client:
        return await getattr(client, method)(step)


def test_fetch_stats_validates_and_flags_incomplete_fields():
    client = client_for({"/stats/field/values": httpx.Response(200, json=fixture("stats_field_values.json"))})
    result = asyncio.run(call(client, "fetch_stats", FieldValuesStep(label="All trials", fields=["Phase", "LeadSponsorName"])))
    assert result.endpoint == "stats/field/values"
    assert result.incomplete_fields == ["LeadSponsorName"]


def test_fetch_stats_for_sizes_and_records():
    client = client_for(
        {
            "/stats/field/sizes": httpx.Response(200, json=fixture("stats_field_sizes.json")),
            "/stats/size": httpx.Response(200, json=fixture("stats_size.json")),
        }
    )
    sizes = asyncio.run(call(client, "fetch_stats", FieldSizesStep(label="Conditions", fields=["Condition"])))
    assert isinstance(sizes.data, FieldSizesResponse)
    client = client_for({"/stats/size": httpx.Response(200, json=fixture("stats_size.json"))})
    records = asyncio.run(call(client, "fetch_stats", RecordSizeStep(label="Record sizes")))
    assert isinstance(records.data, RecordSizesResponse) and records.incomplete_fields == []


def test_unexpected_stats_shape_is_an_upstream_error():
    client = client_for({"/stats/size": httpx.Response(200, json={"surprise": True})})
    with pytest.raises(UpstreamError, match="Unexpected response shape"):
        asyncio.run(call(client, "fetch_stats", RecordSizeStep(label="Record sizes")))


def test_fetch_study_returns_one_trial():
    client = client_for({"/studies/NCT05064059": httpx.Response(200, json=fixture("study_NCT05064059.json"))})
    result = asyncio.run(call(client, "fetch_study", StudyStep(label="One trial", nct_id="nct05064059")))
    assert result.total_matched == 1 and result.trials[0].nct_id == "NCT05064059"


def test_unknown_nct_id_goes_back_to_the_planner():
    client = client_for({})
    with pytest.raises(InvalidSearch, match="Not found: /studies/NCT09999999"):
        asyncio.run(call(client, "fetch_study", StudyStep(label="Missing", nct_id="NCT09999999")))
