"""What the user sends us: a natural-language question plus optional filters."""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TrialPhase(str, Enum):
    """Phase values as ClinicalTrials.gov API v2 spells them."""

    EARLY_PHASE1 = "EARLY_PHASE1"
    PHASE1 = "PHASE1"
    PHASE2 = "PHASE2"
    PHASE3 = "PHASE3"
    PHASE4 = "PHASE4"
    NA = "NA"  # not applicable, e.g. device or behavioral trials


class RecruitmentStatus(str, Enum):
    """Overall status values as ClinicalTrials.gov API v2 spells them."""

    NOT_YET_RECRUITING = "NOT_YET_RECRUITING"
    RECRUITING = "RECRUITING"
    ENROLLING_BY_INVITATION = "ENROLLING_BY_INVITATION"
    ACTIVE_NOT_RECRUITING = "ACTIVE_NOT_RECRUITING"
    COMPLETED = "COMPLETED"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"
    WITHDRAWN = "WITHDRAWN"
    UNKNOWN = "UNKNOWN"


# The enums below are the API's own values (GET /api/v2/studies/enums).


class StudyType(str, Enum):
    INTERVENTIONAL = "INTERVENTIONAL"  # tests a treatment: what most people mean by "trial"
    OBSERVATIONAL = "OBSERVATIONAL"
    EXPANDED_ACCESS = "EXPANDED_ACCESS"


class InterventionType(str, Enum):
    DRUG = "DRUG"
    BIOLOGICAL = "BIOLOGICAL"
    DEVICE = "DEVICE"
    PROCEDURE = "PROCEDURE"
    RADIATION = "RADIATION"
    BEHAVIORAL = "BEHAVIORAL"
    GENETIC = "GENETIC"
    DIETARY_SUPPLEMENT = "DIETARY_SUPPLEMENT"
    COMBINATION_PRODUCT = "COMBINATION_PRODUCT"
    DIAGNOSTIC_TEST = "DIAGNOSTIC_TEST"
    OTHER = "OTHER"


class SponsorClass(str, Enum):
    INDUSTRY = "INDUSTRY"
    NIH = "NIH"
    FED = "FED"  # other US federal agency
    OTHER_GOV = "OTHER_GOV"  # non-US government
    NETWORK = "NETWORK"
    INDIV = "INDIV"  # individual
    OTHER = "OTHER"  # mostly universities and hospitals
    AMBIG = "AMBIG"
    UNKNOWN = "UNKNOWN"


class AgeGroup(str, Enum):
    CHILD = "CHILD"  # under 18
    ADULT = "ADULT"  # 18-64
    OLDER_ADULT = "OLDER_ADULT"  # 65+


class QueryRequest(BaseModel):
    """Request body for POST /query.

    Only `query` is required. Structured fields, when given, take precedence
    over anything the system infers from the question text.
    """

    model_config = ConfigDict(
        extra="forbid",  # reject typos like "drugname" instead of silently ignoring them
        str_strip_whitespace=True,
        json_schema_extra={
            "examples": [
                {
                    "query": "How has the number of trials for this drug changed over time?",
                    "drug_name": "Pembrolizumab",
                }
            ]
        },
    )

    query: str = Field(
        min_length=3,
        max_length=500,
        description="Natural-language question about clinical trials.",
    )
    drug_name: str | None = Field(
        default=None, min_length=1, max_length=200, description="Intervention / drug name, e.g. 'Pembrolizumab'."
    )
    condition: str | None = Field(
        default=None, min_length=1, max_length=200, description="Condition or disease, e.g. 'non-small cell lung cancer'."
    )
    trial_phase: list[TrialPhase] | None = Field(
        default=None, min_length=1, description="Restrict to these phases."
    )
    sponsor: str | None = Field(
        default=None, min_length=1, max_length=200, description="Lead sponsor name, e.g. 'Merck Sharp & Dohme LLC'."
    )
    country: str | None = Field(
        default=None, min_length=2, max_length=100, description="Country where the trial has a site, e.g. 'United States'."
    )
    recruitment_status: list[RecruitmentStatus] | None = Field(
        default=None, min_length=1, description="Restrict to these overall statuses."
    )
    start_year: int | None = Field(
        default=None, ge=1900, le=2100, description="Earliest trial start year (inclusive)."
    )
    end_year: int | None = Field(
        default=None, ge=1900, le=2100, description="Latest trial start year (inclusive)."
    )

    @model_validator(mode="after")
    def check_year_range(self) -> "QueryRequest":
        if self.start_year and self.end_year and self.start_year > self.end_year:
            raise ValueError("start_year must be less than or equal to end_year")
        return self

    def filters(self) -> dict:
        """The structured filters the user actually set (everything except `query`)."""
        return self.model_dump(exclude={"query"}, exclude_none=True, mode="json")
