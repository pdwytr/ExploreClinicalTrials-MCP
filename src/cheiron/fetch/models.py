"""ClinicalTrials.gov Data API v2: what we send and what comes back.

Three layers:
    StudySearchParams  typed request  ->  GET /api/v2/studies query string
    StudiesPage        raw response, only the fields we request (all optional:
                       real records often leave fields out)
    Trial              one study flattened into the values our analysis uses

API docs: https://clinicaltrials.gov/data-api/api
OpenAPI spec: https://clinicaltrials.gov/api/oas/v2
"""

import re
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

from cheiron.models.request import RecruitmentStatus, TrialPhase

BASE_URL = "https://clinicaltrials.gov/api/v2"
MAX_PAGE_SIZE = 1000  # the API silently caps larger values at 1,000

# Fields requested on every search (the API's "piece" names). Keeping the list
# short cuts response size roughly 10x versus returning whole records.
DEFAULT_FIELDS = [
    "NCTId",
    "BriefTitle",
    "OverallStatus",
    "StartDate",
    "Phase",
    "LeadSponsorName",
    "LeadSponsorClass",
    "Condition",
    "InterventionName",
    "InterventionType",
    "LocationCountry",
    "EnrollmentCount",
]

# Where each Trial value comes from in the raw record, for citations.
FIELD_PATHS = {
    "title": "protocolSection.identificationModule.briefTitle",
    "overall_status": "protocolSection.statusModule.overallStatus",
    "start_date": "protocolSection.statusModule.startDateStruct.date",
    "phases": "protocolSection.designModule.phases",
    "lead_sponsor": "protocolSection.sponsorCollaboratorsModule.leadSponsor.name",
    "sponsor_class": "protocolSection.sponsorCollaboratorsModule.leadSponsor.class",
    "conditions": "protocolSection.conditionsModule.conditions",
    "interventions": "protocolSection.armsInterventionsModule.interventions",
    "countries": "protocolSection.contactsLocationsModule.locations.country",
    "enrollment": "protocolSection.designModule.enrollmentInfo.count",
}


# --- Request ---------------------------------------------------------------------


def build_advanced_filter(
    phases: list[TrialPhase] | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
) -> str | None:
    """Phase and start-date filters in Essie syntax, e.g.
    'AREA[Phase](PHASE2 OR PHASE3) AND AREA[StartDate]RANGE[2015-01-01,MAX]'."""
    parts = []
    if phases:
        parts.append(f"AREA[Phase]({' OR '.join(p.value for p in phases)})")
    if start_year or end_year:
        lo = f"{start_year}-01-01" if start_year else "MIN"
        hi = f"{end_year}-12-31" if end_year else "MAX"
        parts.append(f"AREA[StartDate]RANGE[{lo},{hi}]")
    return " AND ".join(parts) or None


class StudySearchParams(BaseModel):
    """Typed version of the GET /studies query string. Text fields use Essie syntax."""

    condition: str | None = Field(default=None, description="query.cond")
    intervention: str | None = Field(default=None, description="query.intr")
    term: str | None = Field(default=None, description="query.term: anything else")
    location: str | None = Field(default=None, description="query.locn, e.g. a country")
    sponsor: str | None = Field(default=None, description="query.spons: lead sponsor or collaborator")
    overall_status: list[RecruitmentStatus] | None = Field(default=None, description="filter.overallStatus")
    advanced: str | None = Field(default=None, description="filter.advanced, see build_advanced_filter")
    fields: list[str] = Field(default_factory=lambda: list(DEFAULT_FIELDS))
    page_size: int = Field(default=MAX_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    page_token: str | None = None
    count_total: bool = True

    def to_query_params(self) -> dict[str, str]:
        params = {
            "query.cond": self.condition,
            "query.intr": self.intervention,
            "query.term": self.term,
            "query.locn": self.location,
            "query.spons": self.sponsor,
            "filter.overallStatus": "|".join(s.value for s in self.overall_status) if self.overall_status else None,
            "filter.advanced": self.advanced,
            "fields": "|".join(self.fields),
            "pageSize": str(self.page_size),
            "pageToken": self.page_token,
            "countTotal": "true" if self.count_total and not self.page_token else None,  # ignored after page 1
        }
        return {k: v for k, v in params.items() if v}


# --- Raw response (mirrors the API's JSON; camelCase on the wire) -----------------


class _Raw(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, validate_by_name=True, extra="ignore")


class DateStruct(_Raw):
    date: str  # "2021-11-10" or a partial date like "2021-11"
    type: str | None = None  # ACTUAL | ESTIMATED


class IdentificationModule(_Raw):
    nct_id: str = Field(alias="nctId")  # to_camel would give "nctId" anyway; explicit for readability
    brief_title: str | None = None


class StatusModule(_Raw):
    overall_status: str | None = None
    start_date_struct: DateStruct | None = None


class LeadSponsor(_Raw):
    name: str | None = None
    sponsor_class: str | None = Field(default=None, alias="class")  # INDUSTRY, NIH, OTHER, ...


class SponsorCollaboratorsModule(_Raw):
    lead_sponsor: LeadSponsor | None = None


class ConditionsModule(_Raw):
    conditions: list[str] = Field(default_factory=list)


class EnrollmentInfo(_Raw):
    count: int | None = None


class DesignModule(_Raw):
    phases: list[str] = Field(default_factory=list)  # kept as strings: unknown values must not crash parsing
    enrollment_info: EnrollmentInfo | None = None


class RawIntervention(_Raw):
    type: str | None = None  # DRUG, BIOLOGICAL, DEVICE, ...
    name: str | None = None


class ArmsInterventionsModule(_Raw):
    interventions: list[RawIntervention] = Field(default_factory=list)


class Location(_Raw):
    country: str | None = None


class ContactsLocationsModule(_Raw):
    locations: list[Location] = Field(default_factory=list)


class ProtocolSection(_Raw):
    identification_module: IdentificationModule
    status_module: StatusModule | None = None
    sponsor_collaborators_module: SponsorCollaboratorsModule | None = None
    conditions_module: ConditionsModule | None = None
    design_module: DesignModule | None = None
    arms_interventions_module: ArmsInterventionsModule | None = None
    contacts_locations_module: ContactsLocationsModule | None = None


class RawStudy(_Raw):
    protocol_section: ProtocolSection


class StudiesPage(_Raw):
    """One page of GET /studies. `total_count` only comes with the first page."""

    studies: list[RawStudy] = Field(default_factory=list)
    total_count: int | None = None
    next_page_token: str | None = None


# --- Normalized trial ---------------------------------------------------------------


class Intervention(BaseModel):
    name: str
    type: str | None = None


class Trial(BaseModel):
    """One study, flattened. Missing values stay None / empty; analysis decides what to skip."""

    nct_id: str = Field(pattern=r"^NCT\d{8}$")
    title: str | None = None
    overall_status: str | None = None
    start_date: date | None = None
    phases: list[str] = Field(default_factory=list)
    lead_sponsor: str | None = None
    sponsor_class: str | None = None
    conditions: list[str] = Field(default_factory=list)
    interventions: list[Intervention] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list, description="Distinct, in order of first appearance.")
    enrollment: int | None = None

    @property
    def start_year(self) -> int | None:
        return self.start_date.year if self.start_date else None

    @field_validator("start_date", mode="before")
    @classmethod
    def parse_partial_date(cls, value):
        """The API mixes full dates with year-month ("2021-11"); the latter becomes the 1st of the month."""
        if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}", value):
            return f"{value}-01"
        return value

    @classmethod
    def from_raw(cls, raw: RawStudy) -> "Trial":
        p = raw.protocol_section
        status = p.status_module or StatusModule()
        sponsor = (p.sponsor_collaborators_module or SponsorCollaboratorsModule()).lead_sponsor or LeadSponsor()
        design = p.design_module or DesignModule()
        locations = (p.contacts_locations_module or ContactsLocationsModule()).locations
        interventions = (p.arms_interventions_module or ArmsInterventionsModule()).interventions
        return cls(
            nct_id=p.identification_module.nct_id,
            title=p.identification_module.brief_title,
            overall_status=status.overall_status,
            start_date=status.start_date_struct.date if status.start_date_struct else None,
            phases=design.phases,
            lead_sponsor=sponsor.name,
            sponsor_class=sponsor.sponsor_class,
            conditions=(p.conditions_module or ConditionsModule()).conditions,
            interventions=[Intervention(name=i.name, type=i.type) for i in interventions if i.name],
            countries=list(dict.fromkeys(loc.country for loc in locations if loc.country)),
            enrollment=design.enrollment_info.count if design.enrollment_info else None,
        )
