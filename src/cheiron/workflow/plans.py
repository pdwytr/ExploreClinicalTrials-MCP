"""The hand-offs between workflow steps.

    SearchPlan   Agent 1 (search planner) -> code: which API calls to make (steps)
    DataProfile  code -> Agent 2: what the fetched data looks like
    ChartPlan    Agent 2 (chart planner) -> code: how to show it
"""

from collections.abc import Callable
from datetime import datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from cheiron.fetch.endpoints import PlanStep
from cheiron.fetch.models import Trial
from cheiron.fetch.stats import StatsResponse
from cheiron.models.response import Intent, VisualizationType

# --- Agent 1 output ------------------------------------------------------------------
#
# Deliberately thin: the planner picks ClinicalTrials.gov endpoints and writes their
# parameters itself (for /studies: query.*, filter.* in Essie syntax), after reading
# the API docs in its prompt. Code checks each step against its endpoint's rules,
# adds the user's structured filters, executes the steps, and sends feedback if a
# step fails or finds nothing.


class SearchPlan(BaseModel):
    steps: list[PlanStep] = Field(
        min_length=1, max_length=4, description="One step, or one per compared side. Each names its endpoint."
    )
    rationale: str = Field(min_length=1, max_length=500, description="What is being fetched and why, in plain words.")

    @property
    def is_comparison(self) -> bool:
        return len(self.steps) > 1

    @model_validator(mode="after")
    def check_plan(self) -> "SearchPlan":
        labels = [s.label.casefold() for s in self.steps]
        if len(set(labels)) != len(labels):
            raise ValueError("step labels must be unique")
        if self.is_comparison:
            identities = {s.model_dump_json(exclude={"label"}) for s in self.steps}
            if len(identities) != len(self.steps):
                raise ValueError("compared steps must differ")
        return self


class Unanswerable(BaseModel):
    """The agent's answer when registry records cannot answer the question
    (e.g. "Is drug X effective?", or "this drug" with no drug given)."""

    reason: str = Field(min_length=1, max_length=300)


# --- Progress (for task status) --------------------------------------------------------


class Progress(BaseModel):
    """Where a query is, for status updates. Stages run in this order; failed can end any of them."""

    stage: Literal["queued", "planning", "fetching", "analyzing", "building", "saving", "done", "failed"]
    message: str
    trials_fetched: int | None = None
    trials_total: int | None = None


ProgressCallback = Callable[[Progress], None]


# --- Fetch result and profile ---------------------------------------------------------


class FetchResult(BaseModel):
    """Trials from a /studies search or a single-study lookup."""

    trials: list[Trial]
    total_matched: int = Field(ge=0, description="Matches at the source, may exceed len(trials).")

    @property
    def truncated(self) -> bool:
        return self.total_matched > len(self.trials)


class StatsResult(BaseModel):
    """A validated registry-wide /stats response."""

    endpoint: str
    data: StatsResponse
    incomplete_fields: list[str] = Field(default_factory=list, description="Fields the API cut off (top values only).")


StepResult = FetchResult | StatsResult


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
    GROUP = "group"  # the search label: the series in a comparison


class NumericSummary(BaseModel):
    min: float
    median: float
    max: float


class FieldProfile(BaseModel):
    distinct: int = Field(ge=0)
    missing: int = Field(ge=0, description="Trials with no value for this dimension.")
    top_values: list[tuple[str, int]] = Field(
        default_factory=list, description="Most frequent values with the number of trials having each."
    )
    multi_valued: bool = Field(
        default=False, description="A trial can have several values, so per-value counts can sum to more than the trials."
    )
    numeric: NumericSummary | None = None
    missing_by_group: dict[str, int] | None = Field(default=None, description="Per comparison side, when there are several.")


class StatsFieldSummary(BaseModel):
    piece: str
    type: str
    missing: int
    distinct: int | None = None
    top_values: list[tuple[str, int]] = Field(default_factory=list)
    incomplete: bool = Field(default=False, description="The API returned only the top values.")
    min: str | float | None = None
    max: str | float | None = None
    avg: float | None = None


class StatsSummary(BaseModel):
    """A registry-wide /stats result, summarised."""

    label: str
    endpoint: str
    fields: list[StatsFieldSummary] = Field(default_factory=list)
    note: str | None = None  # for stats/size, which has no fields


class DataProfile(BaseModel):
    """A compact summary of everything fetched, small enough for an LLM prompt. Never trial records."""

    total_matched: int = Field(ge=0)
    trials_fetched: int = Field(ge=0)
    group_sizes: dict[str, int]
    fields: dict[Dimension, FieldProfile]
    stats: list[StatsSummary] = Field(default_factory=list)
    data_as_of: datetime | None = None


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
    def renderable(self) -> "ChartPlan":
        """Structural rules: what each chart type needs to be drawn from trial counts.
        Which chart fits which question is the chart-planning skill's job, not code's."""
        needs_series = self.chart_type in ("grouped_bar_chart", "stacked_bar_chart", "network_graph")
        if needs_series and self.series is None:
            raise ValueError(f"{self.chart_type} needs a series dimension")
        if self.chart_type == "time_series" and self.x is not Dimension.START_YEAR:
            raise ValueError("time_series needs x = start_year")
        if self.chart_type == "histogram" and self.x is not Dimension.ENROLLMENT:
            raise ValueError("histogram needs x = enrollment (the only numeric field)")
        if self.chart_type == "scatter_plot":
            raise ValueError("scatter_plot needs two numeric fields per trial; only enrollment is numeric")
        if Dimension.ENROLLMENT in (self.x, self.series) and self.chart_type != "histogram":
            raise ValueError("enrollment is numeric: chart it as a histogram")
        if self.series is not None and self.series == self.x and self.chart_type != "network_graph":
            raise ValueError("series must differ from x (the same field twice only makes sense in a network)")
        return self
