"""The hand-offs between workflow steps.

    SearchPlan   Agent 1 (search planner) -> code: which API calls to make (steps)
    DataProfile  code -> Agent 2: what the fetched data looks like
    ChartPlan    Agent 2 (chart planner) -> code: how to show it
"""

from collections.abc import Callable
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from cheiron.fetch.endpoints import PlanStep
from cheiron.fetch.models import Trial
from cheiron.fetch.stats import StatsResponse
from cheiron.models.catalog import INTENT_CHART_TYPES, Intent, VisualizationType

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


# What the search planner's LLM returns: a plan, or a reason the question can't be
# answered from trial records (e.g. "Is drug X effective?", or "this drug" with no drug given).


class SearchDecision(BaseModel):
    kind: Literal["search"] = "search"
    plan: SearchPlan


class Unanswerable(BaseModel):
    kind: Literal["unanswerable"] = "unanswerable"
    reason: str = Field(min_length=1, max_length=300)


SearchPlannerOutput = Annotated[SearchDecision | Unanswerable, Field(discriminator="kind")]


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
