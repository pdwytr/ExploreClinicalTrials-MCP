"""The hand-offs between workflow steps.

    SearchPlan   Agent 1 (search planner) -> code: what to look for
    DataProfile  code -> Agent 2: what the fetched data looks like
    ChartPlan    Agent 2 (chart planner) -> code: how to show it
"""

from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

from cheiron.fetch.models import Trial
from cheiron.models.catalog import INTENT_CHART_TYPES, Intent, VisualizationType
from cheiron.models.request import (
    AgeGroup,
    InterventionType,
    RecruitmentStatus,
    SponsorClass,
    StudyType,
    TrialPhase,
)

# --- Agent 1 output ------------------------------------------------------------------
#
# Design rules (each checked by a validator or by the translation code):
#   - The agent writes plain terms, never API syntax: lists are OR-ed and quoted by code.
#   - Groups exist only for comparisons of *searched terms* (drug A vs drug B,
#     condition X vs Y): those are different result sets. Comparisons of trial
#     *attributes* (phase, sponsor class, status, year) are one search plus a chart
#     dimension, not groups.
#   - Fixed-value filters apply to every group.
#   - A plan must narrow the registry (610k+ trials) with at least one term or filter.

Term = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
TermList = Annotated[list[Term], Field(max_length=10)]


def _dedupe(terms: list[str]) -> list[str]:
    seen, out = set(), []
    for t in terms:
        if t.casefold() not in seen:
            seen.add(t.casefold())
            out.append(t)
    return out


class SearchTerms(BaseModel):
    """Free-text search terms. Within a list: any term matches (OR). Across lists: all must match (AND).

    Write names as people say them; do not add synonyms or brand names, the API
    already matches them (searching 'Keytruda' and 'pembrolizumab' returns the same trials).
    """

    conditions: TermList = Field(default_factory=list, description="Diseases or conditions studied. API: query.cond")
    interventions: TermList = Field(
        default_factory=list, description="Drugs, biologics, devices, procedures. API: query.intr"
    )
    sponsors: TermList = Field(default_factory=list, description="Sponsor or collaborator organisations. API: query.spons")
    locations: TermList = Field(
        default_factory=list,
        description="Countries, states or cities with a trial site. Expand regions to countries "
        "('Europe' matches facility names, not the continent). API: query.locn",
    )
    keywords: TermList = Field(default_factory=list, description="Anything that fits no other list. API: query.term")

    @field_validator("conditions", "interventions", "sponsors", "locations", "keywords")
    @classmethod
    def dedupe(cls, terms: list[str]) -> list[str]:
        return _dedupe(terms)

    def is_empty(self) -> bool:
        return not any((self.conditions, self.interventions, self.sponsors, self.locations, self.keywords))

    def signature(self) -> tuple:
        """Case-insensitive identity of the terms, to spot duplicate groups."""
        return tuple(
            frozenset(t.casefold() for t in terms)
            for terms in (self.conditions, self.interventions, self.sponsors, self.locations, self.keywords)
        )


class SearchGroup(SearchTerms):
    """One set of trials to fetch. A comparison has one group per side."""

    label: str = Field(min_length=1, max_length=80, description="Shown in the chart, e.g. 'Nivolumab'.")


class SearchPlan(BaseModel):
    groups: list[SearchGroup] = Field(min_length=1, max_length=4, description="One group, or one per compared side.")

    # Fixed-value filters, applied to every group. Unset = no filter.
    phases: list[TrialPhase] | None = Field(default=None, min_length=1)
    statuses: list[RecruitmentStatus] | None = Field(
        default=None, min_length=1, description="'ongoing' = NOT_YET_RECRUITING, RECRUITING, ENROLLING_BY_INVITATION, ACTIVE_NOT_RECRUITING."
    )
    study_types: list[StudyType] | None = Field(default=None, min_length=1)
    intervention_types: list[InterventionType] | None = Field(default=None, min_length=1)
    sponsor_classes: list[SponsorClass] | None = Field(default=None, min_length=1)
    age_groups: list[AgeGroup] | None = Field(default=None, min_length=1)
    start_year: int | None = Field(default=None, ge=1900, le=2100, description="Trial start year, inclusive.")
    end_year: int | None = Field(default=None, ge=1900, le=2100, description="Trial start year, inclusive.")

    @property
    def is_comparison(self) -> bool:
        return len(self.groups) > 1

    def has_filters(self) -> bool:
        fixed = (self.phases, self.statuses, self.study_types, self.intervention_types, self.sponsor_classes, self.age_groups)
        return any(fixed) or self.start_year is not None or self.end_year is not None

    @model_validator(mode="after")
    def check_plan(self) -> "SearchPlan":
        labels = [g.label.casefold() for g in self.groups]
        if len(set(labels)) != len(labels):
            raise ValueError("group labels must be unique")
        if self.start_year and self.end_year and self.start_year > self.end_year:
            raise ValueError("start_year must be less than or equal to end_year")
        if self.is_comparison:
            if any(g.is_empty() for g in self.groups):
                raise ValueError("every compared group needs at least one search term")
            if len({g.signature() for g in self.groups}) != len(self.groups):
                raise ValueError("compared groups must search for different terms")
        elif self.groups[0].is_empty() and not self.has_filters():
            raise ValueError("plan must narrow the search with at least one term or filter")
        return self


# What the search planner's LLM returns: a plan, or a reason the question can't be
# answered from trial records (e.g. "Is drug X effective?", or "this drug" with no drug given).


class SearchDecision(BaseModel):
    kind: Literal["search"] = "search"
    plan: SearchPlan


class Unanswerable(BaseModel):
    kind: Literal["unanswerable"] = "unanswerable"
    reason: str = Field(min_length=1, max_length=300)


SearchPlannerOutput = Annotated[SearchDecision | Unanswerable, Field(discriminator="kind")]


# --- Fetch result and profile ---------------------------------------------------------


class FetchResult(BaseModel):
    trials: list[Trial]
    total_matched: int = Field(ge=0, description="Matches at the source, may exceed len(trials).")

    @property
    def truncated(self) -> bool:
        return self.total_matched > len(self.trials)


class Dimension(str, Enum):
    """Trial attributes a chart can group or plot by."""

    PHASE = "phase"
    START_YEAR = "start_year"
    STATUS = "overall_status"
    SPONSOR = "lead_sponsor"
    SPONSOR_CLASS = "sponsor_class"
    CONDITION = "condition"
    INTERVENTION = "intervention"
    INTERVENTION_TYPE = "intervention_type"
    COUNTRY = "country"
    ENROLLMENT = "enrollment"
    GROUP = "group"  # the SearchGroup label: the series in a comparison


class FieldProfile(BaseModel):
    distinct: int = Field(ge=0)
    missing: int = Field(ge=0, description="Trials with no value for this dimension.")
    top_values: list[tuple[str, int]] = Field(default_factory=list, description="Most frequent values with counts.")


class DataProfile(BaseModel):
    """A compact summary of the fetched trials, small enough for an LLM prompt."""

    total_matched: int = Field(ge=0)
    trials_fetched: int = Field(ge=0)
    group_sizes: dict[str, int]
    fields: dict[Dimension, FieldProfile]


# --- Agent 2 output ---------------------------------------------------------------------


class ChartPlan(BaseModel):
    """What to draw. For network graphs, `x` and `series` are the two node kinds
    (e.g. lead_sponsor <-> intervention; the same dimension twice = co-occurrence)."""

    intent: Intent
    chart_type: VisualizationType
    title: str = Field(min_length=1, max_length=120)
    x: Dimension
    series: Dimension | None = None
    top_n: int | None = Field(default=None, ge=1, le=50, description="Keep only the N largest categories.")

    @model_validator(mode="after")
    def fits_catalog(self) -> "ChartPlan":
        if self.chart_type not in INTENT_CHART_TYPES[self.intent]:
            raise ValueError(f"{self.chart_type} does not fit intent {self.intent.value}")
        needs_series = self.chart_type in ("grouped_bar_chart", "stacked_bar_chart", "network_graph")
        if needs_series and self.series is None:
            raise ValueError(f"{self.chart_type} needs a series dimension")
        return self
