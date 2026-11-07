"""The hand-offs between workflow steps.

    SearchPlan   Agent 1 (search planner) -> code: what to look for
    DataProfile  code -> Agent 2: what the fetched data looks like
    ChartPlan    Agent 2 (chart planner) -> code: how to show it
"""

from enum import Enum

from pydantic import BaseModel, Field, model_validator

from cheiron.fetch.models import Trial
from cheiron.models.catalog import INTENT_CHART_TYPES, Intent, VisualizationType
from cheiron.models.request import RecruitmentStatus, TrialPhase

# --- Agent 1 output ------------------------------------------------------------------


class SearchGroup(BaseModel):
    """One set of trials to fetch. A comparison ("A vs B") has one group per side."""

    label: str = Field(min_length=1, max_length=80, description="Shown in the chart, e.g. 'Nivolumab'.")
    condition: str | None = None
    intervention: str | None = None
    sponsor: str | None = None
    location: str | None = None
    term: str | None = Field(default=None, description="Anything that fits no other field.")


class SearchPlan(BaseModel):
    groups: list[SearchGroup] = Field(min_length=1, max_length=4)
    phases: list[TrialPhase] | None = None
    statuses: list[RecruitmentStatus] | None = None
    start_year: int | None = Field(default=None, ge=1900, le=2100)
    end_year: int | None = Field(default=None, ge=1900, le=2100)
    interpretation: str = Field(description="Plain-English restatement of the search, for meta.")

    @property
    def is_comparison(self) -> bool:
        return len(self.groups) > 1

    @model_validator(mode="after")
    def labels_are_unique(self) -> "SearchPlan":
        labels = [g.label for g in self.groups]
        if len(set(labels)) != len(labels):
            raise ValueError("group labels must be unique")
        return self


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
