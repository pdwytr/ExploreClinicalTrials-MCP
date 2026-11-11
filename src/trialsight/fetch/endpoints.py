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

from trialsight.models.request import RecruitmentStatus, TrialPhase

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
# Things that have their own slot: written in `advanced`, they would bypass the slot's rules.
_SLOTTED_IN_TEXT = {
    "AREA[Phase]": "phases",
    "AREA[StudyType]": "study_type",
    "AREA[OverallStatus]": "statuses",
    "AREA[EnrollmentCount]": "min_enrollment / max_enrollment",
    "AREA[LeadSponsorName]": "sponsors",
    "AREA[InterventionName]": "drugs",
    "AREA[Condition]": "conditions",
    "AREA[LocationCountry]": "countries",
}

Region = Literal["europe", "asia", "africa", "north_america", "south_america", "oceania"]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class StudiesStep(_Step):
    """Search trials, stated as what the question means. Code resolves the names to the registry's
    own (brand -> generic, alias -> registered sponsor), adds the user's structured fields and
    compiles the API parameters; the planner never writes query.* parameters itself.

    Within a slot the values are alternatives (OR), except drugs with drugs_match="all"
    (combination therapy: every drug in the same trial). Slots combine with AND."""

    endpoint: Literal["studies"] = "studies"
    drugs: list[Name] = Field(default_factory=list, description="Drugs or other interventions, e.g. ['semaglutide'].")
    drugs_match: Literal["any", "all"] = Field(default="any", description="'all' = tested together in one trial.")
    exclude_drugs: list[Name] = Field(default_factory=list)
    conditions: list[Name] = Field(default_factory=list, description="Diseases or conditions, e.g. ['type 2 diabetes'].")
    exclude_conditions: list[Name] = Field(default_factory=list, description="e.g. ['type 1 diabetes'].")
    sponsors: list[Name] = Field(default_factory=list, description="LEAD sponsors, e.g. ['Pfizer'].")
    countries: list[Name] = Field(default_factory=list, description="Countries with a trial site, e.g. ['Japan'].")
    region: Region | None = Field(default=None, description="A region; code expands it into its countries.")
    phases: list[TrialPhase] = Field(default_factory=list)
    statuses: list[RecruitmentStatus] = Field(default_factory=list)
    study_type: Literal["any", "interventional", "observational"] = Field(
        default="any", description="'interventional' only when the question asks for treatment trials explicitly."
    )
    min_enrollment: int | None = Field(default=None, ge=0)
    max_enrollment: int | None = Field(default=None, ge=0)
    period: Period | None = Field(default=None, description="Year range on start or completion date.")
    keywords: list[Name] = Field(default_factory=list, description="Other search words (acronyms, 'CAR-T'): query.term.")
    advanced: str | None = Field(
        default=None,
        max_length=500,
        description="Escape hatch: an Essie expression for a filter no slot covers (design, counters). Shown to the reader.",
    )

    @model_validator(mode="after")
    def check_step(self) -> "StudiesStep":
        if self.exclude_drugs and not self.drugs or self.exclude_conditions and not self.conditions:
            raise ValueError("exclude_drugs / exclude_conditions need drugs / conditions to exclude from")
        slots = (self.drugs, self.conditions, self.sponsors, self.countries, self.phases, self.statuses, self.keywords)
        if not any(slots) and not (self.region or self.advanced or self.period or self.study_type != "any"):
            raise ValueError("a studies step needs at least one search slot (drugs, conditions, sponsors, ...)")
        if self.min_enrollment is not None and self.max_enrollment is not None and self.min_enrollment > self.max_enrollment:
            raise ValueError("min_enrollment must be at most max_enrollment")
        if self.advanced:
            if _DATE_RANGE_IN_TEXT.search(self.advanced):
                raise ValueError("put year ranges in 'period' (field start or completion), not in advanced")
            for area, slot in _SLOTTED_IN_TEXT.items():
                if area.casefold() in self.advanced.casefold():
                    raise ValueError(f"use the '{slot}' slot instead of {area} in advanced")
        return self

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
