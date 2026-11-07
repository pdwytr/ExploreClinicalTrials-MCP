"""Response models for the registry-wide /stats endpoints, from the OpenAPI spec's schemas.

Every /stats response is validated against these before it is used or stored.
Live behaviour worth knowing (checked 2026-11-07):
  - /stats/field/values returns counts only for ENUM and STRING fields, and STRING
    fields are capped at the top 250 values (LeadSponsorName: 250 of 52,731).
  - DATE fields return only min/max; INTEGER/NUMBER only min/max/avg: no distribution.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel
from pydantic.alias_generators import to_camel


class _Raw(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, validate_by_name=True, serialize_by_alias=True, extra="ignore")


# --- /stats/field/values -------------------------------------------------------------------


class ValueCount(_Raw):
    value: str
    studies_count: int


class LongestString(_Raw):
    length: int
    nct_id: str = Field(alias="nctId")
    value: str


class _FieldStats(_Raw):
    field: str
    piece: str
    missing_studies_count: int


class EnumStats(_FieldStats):
    type: Literal["ENUM"]
    unique_values_count: int
    top_values: list[ValueCount] = Field(default_factory=list)


class StringStats(_FieldStats):
    type: Literal["STRING"]
    unique_values_count: int
    top_values: list[ValueCount] = Field(default_factory=list)
    longest: LongestString | None = None


class DateStats(_FieldStats):
    type: Literal["DATE"]
    formats: list[str]
    min: str | None = None
    max: str | None = None


class IntegerStats(_FieldStats):
    type: Literal["INTEGER"]
    min: int | None = None
    max: int | None = None
    avg: float | None = None


class NumberStats(_FieldStats):
    type: Literal["NUMBER"]
    min: float | None = None
    max: float | None = None
    avg: float | None = None


class BooleanStats(_FieldStats):
    type: Literal["BOOLEAN"]
    true_count: int
    false_count: int


FieldValues = Annotated[
    EnumStats | StringStats | DateStats | IntegerStats | NumberStats | BooleanStats, Field(discriminator="type")
]


class FieldValuesResponse(RootModel[list[FieldValues]]):
    pass


# --- /stats/field/sizes ----------------------------------------------------------------------


class ListSize(_Raw):
    size: int
    studies_count: int


class ListSizes(_Raw):
    field: str
    piece: str
    unique_sizes_count: int
    min_size: int | None = None
    max_size: int | None = None
    top_sizes: list[ListSize] = Field(default_factory=list)


class FieldSizesResponse(RootModel[list[ListSizes]]):
    pass


# --- /stats/size ---------------------------------------------------------------------------------


class StudySize(_Raw):
    id: str
    size_bytes: int


class DistItem(_Raw):
    size_range: str
    studies_count: int


class RecordSizesResponse(_Raw):
    average_size_bytes: int
    largest_studies: list[StudySize]
    percentiles: dict[str, int]
    ranges: list[DistItem]
    total_studies: int


StatsResponse = FieldValuesResponse | FieldSizesResponse | RecordSizesResponse

RESPONSE_MODELS: dict[str, type[StatsResponse]] = {
    "stats/field/values": FieldValuesResponse,
    "stats/field/sizes": FieldSizesResponse,
    "stats/size": RecordSizesResponse,
}


def incomplete_fields(response: StatsResponse) -> list[str]:
    """Fields whose counts were cut off by the API (fewer values returned than exist)."""
    if isinstance(response, FieldValuesResponse):
        return [
            f.piece
            for f in response.root
            if isinstance(f, EnumStats | StringStats) and len(f.top_values) < f.unique_values_count
        ]
    if isinstance(response, FieldSizesResponse):
        return [f.piece for f in response.root if len(f.top_sizes) < f.unique_sizes_count]
    return []
