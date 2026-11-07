"""The ClinicalTrials.gov endpoints a plan step may call, and exactly what each accepts.

Rules are copied from the OpenAPI spec (docs/ctgov/openapi.yaml); tests keep them in sync.
Paging, field selection and output format stay with code, never the planner.

    studies              GET /studies              search trials (the only endpoint that filters)
    study                GET /studies/{nctId}      one trial by NCT number
    stats/field/values   GET /stats/field/values   value counts of fields across the WHOLE registry
                                                   (top values only; no search filters)
    stats/field/sizes    GET /stats/field/sizes    sizes of list fields across the whole registry
    stats/size           GET /stats/size           study record sizes across the whole registry
"""

import re
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

from cheiron.fetch.models import check_search_params

# Patterns from the spec: `fields` items and the `nctId` path parameter.
FIELD_NAME_PATTERN = r"^[a-zA-Z][a-zA-Z0-9\-. ]*$"
NCT_ID_PATTERN = r"^[Nn][Cc][Tt]0*[1-9]\d{0,7}$"

FieldName = Annotated[str, StringConstraints(pattern=FIELD_NAME_PATTERN, max_length=100)]


class FieldStatsType(str, Enum):
    """Values of `types` on /stats/field/values (spec schema FieldStatsType)."""

    ENUM = "ENUM"
    STRING = "STRING"
    DATE = "DATE"
    INTEGER = "INTEGER"
    NUMBER = "NUMBER"
    BOOLEAN = "BOOLEAN"


class _Step(BaseModel):
    label: str = Field(min_length=1, max_length=80, description="Shown in the chart, e.g. 'Nivolumab'.")


class Period(BaseModel):
    """A year range on one date field. Code turns it into AREA[StartDate|CompletionDate]RANGE[...]."""

    field: Literal["start", "completion"] = Field(description="Which date the years refer to.")
    from_year: int | None = Field(default=None, ge=1900, le=2100, description="Inclusive.")
    to_year: int | None = Field(default=None, ge=1900, le=2100, description="Inclusive.")

    @model_validator(mode="after")
    def ordered(self) -> "Period":
        if self.from_year and self.to_year and self.from_year > self.to_year:
            raise ValueError("from_year must be less than or equal to to_year")
        return self


_DATE_RANGE_IN_TEXT = re.compile(r"AREA\[(StartDate|CompletionDate|PrimaryCompletionDate)\]", re.IGNORECASE)


class StudiesStep(_Step):
    """Search trials. The only step that can apply search filters (and the user's filters)."""

    endpoint: Literal["studies"] = "studies"
    params: dict[str, str] = Field(min_length=1, description="query.* / filter.* parameters in Essie syntax.")
    period: Period | None = Field(default=None, description="Year range on start or completion date.")

    @field_validator("params")
    @classmethod
    def known_params(cls, params: dict[str, str]) -> dict[str, str]:
        params = check_search_params(params)
        for value in params.values():
            if _DATE_RANGE_IN_TEXT.search(value):
                raise ValueError("put year ranges in 'period' (field start or completion), not in the query text")
        return params

    def path(self) -> str:
        return "/studies"


class StudyStep(_Step):
    """One trial by NCT number."""

    endpoint: Literal["study"] = "study"
    nct_id: str = Field(pattern=NCT_ID_PATTERN, examples=["NCT05064059"])

    def path(self) -> str:
        return f"/studies/{self.nct_id.upper()}"

    def query_params(self) -> dict[str, str]:
        return {}


class FieldValuesStep(_Step):
    """Value counts for fields across the whole registry, e.g. fields=['Phase']."""

    endpoint: Literal["stats/field/values"] = "stats/field/values"
    fields: list[FieldName] = Field(min_length=1, max_length=20, description="Piece names or field paths.")
    types: list[FieldStatsType] | None = Field(default=None, min_length=1)

    def path(self) -> str:
        return "/stats/field/values"

    def query_params(self) -> dict[str, str]:
        params = {"fields": "|".join(self.fields)}
        if self.types:
            params["types"] = "|".join(t.value for t in self.types)
        return params


class FieldSizesStep(_Step):
    """Sizes of list fields across the whole registry, e.g. how many conditions a trial lists."""

    endpoint: Literal["stats/field/sizes"] = "stats/field/sizes"
    fields: list[FieldName] = Field(min_length=1, max_length=20)

    def path(self) -> str:
        return "/stats/field/sizes"

    def query_params(self) -> dict[str, str]:
        return {"fields": "|".join(self.fields)}


class RecordSizeStep(_Step):
    """Study record sizes across the whole registry."""

    endpoint: Literal["stats/size"] = "stats/size"

    def path(self) -> str:
        return "/stats/size"

    def query_params(self) -> dict[str, str]:
        return {}


PlanStep = Annotated[
    StudiesStep | StudyStep | FieldValuesStep | FieldSizesStep | RecordSizeStep,
    Field(discriminator="endpoint"),
]
