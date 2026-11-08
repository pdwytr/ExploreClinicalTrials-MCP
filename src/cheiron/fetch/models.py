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
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel

from cheiron.models.request import RecruitmentStatus, TrialPhase

BASE_URL = "https://clinicaltrials.gov/api/v2"
MAX_PAGE_SIZE = 1000  # the API silently caps larger values at 1,000

# API version that docs/ctgov/ and the ctgov-search skill were generated from.
# A test keeps this equal to docs/ctgov/version.json and the skill's metadata.
SNAPSHOT_API_VERSION = "2.0.5"


class DataVersion(BaseModel):
    """GET /version: the API release and when the registry data was last refreshed (daily)."""

    model_config = ConfigDict(alias_generator=to_camel, validate_by_name=True)

    api_version: str
    data_timestamp: datetime

# Fields requested on every search (the API's "piece" names). Keeping the list
# short cuts response size roughly 10x versus returning whole records.
DEFAULT_FIELDS = [
    "NCTId",
    "BriefTitle",
    "OverallStatus",
    "StartDate",
    "StartDateType",
    "CompletionDate",
    "CompletionDateType",
    "Phase",
    "LeadSponsorName",
    "LeadSponsorClass",
    "Condition",
    "InterventionName",
    "InterventionType",
    "LocationCountry",
    "EnrollmentCount",
    "ConditionMeshTerm",  # the registry's standard (MeSH) names, used to resolve brands and spellings
    "InterventionMeshTerm",
]


# --- Request ---------------------------------------------------------------------


def build_advanced_filter(phases: list[TrialPhase] | None = None) -> str | None:
    """The user's phase filter in Essie syntax, e.g. 'AREA[Phase](PHASE2 OR PHASE3)'."""
    return f"AREA[Phase]({' OR '.join(p.value for p in phases)})" if phases else None


# Date fields a period can be on (the API piece names).
DATE_AREAS = {"start": "StartDate", "completion": "CompletionDate"}


def date_range(field: str, from_year: int | None, to_year: int | None) -> str:
    """A year range on a date field in Essie syntax, e.g. 'AREA[StartDate]RANGE[2015-01-01,MAX]'."""
    lo = f"{from_year}-01-01" if from_year else "MIN"
    hi = f"{to_year}-12-31" if to_year else "MAX"
    return f"AREA[{DATE_AREAS[field]}]RANGE[{lo},{hi}]"


# Search parameters a planner may set on GET /studies (names as the API spells them).
# Paging, field selection, sorting and output format are reserved for code.
SEARCH_PARAMS = frozenset(
    {
        "query.cond",
        "query.term",
        "query.locn",
        "query.titles",
        "query.intr",
        "query.outc",
        "query.spons",
        "query.lead",
        "query.id",
        "filter.overallStatus",
        "filter.geo",
        "filter.ids",
        "filter.advanced",
    }
)
_STATUSES = {s.value for s in RecruitmentStatus}


def check_search_params(search: dict[str, str]) -> dict[str, str]:
    """Reject unknown parameter names, empty values and invalid statuses; trim values."""
    unknown = sorted(set(search) - SEARCH_PARAMS)
    if unknown:
        raise ValueError(f"unknown or reserved parameter(s): {unknown}; allowed: {sorted(SEARCH_PARAMS)}")
    cleaned = {k: v.strip() for k, v in search.items()}
    empty = sorted(k for k, v in cleaned.items() if not v)
    if empty:
        raise ValueError(f"empty value for: {empty}")
    if "filter.overallStatus" in cleaned:
        bad = [s for s in re.split(r"[,|]", cleaned["filter.overallStatus"]) if s.strip() not in _STATUSES]
        if bad:
            raise ValueError(f"invalid status value(s): {bad}; allowed: {sorted(_STATUSES)}")
    return cleaned


class StudySearchParams(BaseModel):
    """One GET /studies request: search parameters (query.*, filter.*) plus paging set by code."""

    search: dict[str, str] = Field(default_factory=dict, description="API search parameters, Essie syntax.")
    fields: list[str] = Field(default_factory=lambda: list(DEFAULT_FIELDS))
    page_size: int = Field(default=MAX_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    page_token: str | None = None
    count_total: bool = True
    # What the search means, for meta and evals (never sent to the API): the agent's slots after
    # the user's fields were merged, names also searched under the registry's standard name, and
    # the site countries it is limited to (registry spellings).
    intent: dict | None = None
    searched_as: dict[str, list[str]] = Field(default_factory=dict)
    countries: list[str] = Field(default_factory=list)

    @field_validator("search")
    @classmethod
    def known_params(cls, search: dict[str, str]) -> dict[str, str]:
        return check_search_params(search)

    def to_query_params(self) -> dict[str, str]:
        params = {
            **self.search,
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
    completion_date_struct: DateStruct | None = None


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


class MeshTerm(_Raw):
    term: str | None = None


class BrowseModule(_Raw):
    meshes: list[MeshTerm] = Field(default_factory=list)


class DerivedSection(_Raw):
    """Fields the registry derives from each record, e.g. the MeSH terms it indexed it under."""

    condition_browse_module: BrowseModule | None = None
    intervention_browse_module: BrowseModule | None = None


class RawStudy(_Raw):
    protocol_section: ProtocolSection
    derived_section: DerivedSection | None = None


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
    start_date_text: str | None = None  # the registry's own text ("2018-03"), quoted by citations
    start_date_type: str | None = None  # ACTUAL or ESTIMATED
    completion_date: date | None = None
    completion_date_text: str | None = None
    completion_date_type: str | None = None
    phases: list[str] = Field(default_factory=list)
    lead_sponsor: str | None = None
    sponsor_class: str | None = None
    conditions: list[str] = Field(default_factory=list)
    interventions: list[Intervention] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list, description="Distinct, in order of first appearance.")
    enrollment: int | None = None
    condition_mesh: list[str] = Field(default_factory=list, description="MeSH terms the registry indexed it under.")
    intervention_mesh: list[str] = Field(default_factory=list)

    @property
    def start_year(self) -> int | None:
        return self.start_date.year if self.start_date else None

    @property
    def completion_year(self) -> int | None:
        return self.completion_date.year if self.completion_date else None

    @model_validator(mode="before")
    @classmethod
    def keep_date_text(cls, data):
        """Remember each date exactly as the registry wrote it before it is parsed (and maybe padded)."""
        if isinstance(data, dict):
            for name in ("start_date", "completion_date"):
                if isinstance(data.get(name), str) and not data.get(f"{name}_text"):
                    data = {**data, f"{name}_text": data[name]}
        return data

    @field_validator("start_date", "completion_date", mode="before")
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
        derived = raw.derived_section or DerivedSection()

        def mesh(module: BrowseModule | None) -> list[str]:
            return list(dict.fromkeys(m.term for m in (module.meshes if module else []) if m.term))

        return cls(
            nct_id=p.identification_module.nct_id,
            title=p.identification_module.brief_title,
            overall_status=status.overall_status,
            start_date=status.start_date_struct.date if status.start_date_struct else None,
            start_date_type=status.start_date_struct.type if status.start_date_struct else None,
            completion_date=status.completion_date_struct.date if status.completion_date_struct else None,
            completion_date_type=status.completion_date_struct.type if status.completion_date_struct else None,
            phases=design.phases,
            lead_sponsor=sponsor.name,
            sponsor_class=sponsor.sponsor_class,
            conditions=(p.conditions_module or ConditionsModule()).conditions,
            interventions=[Intervention(name=i.name, type=i.type) for i in interventions if i.name],
            countries=list(dict.fromkeys(loc.country for loc in locations if loc.country)),
            enrollment=design.enrollment_info.count if design.enrollment_info else None,
            condition_mesh=mesh(derived.condition_browse_module),
            intervention_mesh=mesh(derived.intervention_browse_module),
        )
