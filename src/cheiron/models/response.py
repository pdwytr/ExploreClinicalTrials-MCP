"""What we send back: a visualization spec a frontend can render without guessing.

Shape:
    QueryResponse
    ├── visualization   ChartVisualization | NetworkVisualization  (picked by `type`)
    │   ├── type, intent, title
    │   ├── encoding    which data field goes on which visual channel (Vega-Lite names)
    │   └── data        rows (charts) or a NetworkX node-link graph (network)
    │                   every row / node / edge may carry `citations`
    ├── meta            filters, interpretation, counts, units
    └── vega_lite       ready-to-render Vega-Lite v5 spec, generated from `visualization`
                        (null for network graphs; Vega-Lite has no node-link layout)

Chart data arrives pre-aggregated: one row per bar / point / time bucket, so each
row can carry the citations behind its value.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_serializer, model_validator

# --- Chart vocabulary ----------------------------------------------------------
# Which chart suits which question is judgement, taught by the chart-planning skill;
# code only enforces what makes a chart renderable.

ChartType = Literal[
    "bar_chart",
    "grouped_bar_chart",
    "stacked_bar_chart",
    "time_series",
    "scatter_plot",
    "histogram",
]
VisualizationType = ChartType | Literal["network_graph"]


class Intent(str, Enum):
    """What a chart shows (Financial Times Visual Vocabulary categories); a label for the reader."""

    CHANGE_OVER_TIME = "change_over_time"
    RANKING = "ranking"
    DISTRIBUTION = "distribution"
    MAGNITUDE = "magnitude"
    PART_TO_WHOLE = "part_to_whole"
    CORRELATION = "correlation"
    SPATIAL = "spatial"
    RELATIONSHIP = "relationship"


# --- Citations (bonus: deep traceability) ------------------------------------


class Citation(BaseModel):
    """One trial record that contributed to a data point."""

    nct_id: str = Field(pattern=r"^NCT\d{8}$", examples=["NCT01234567"])
    excerpt: str = Field(description="Exact text or value taken from the API response.")
    field: str | None = Field(
        default=None,
        description="API field path the excerpt came from.",
        examples=["protocolSection.designModule.phases"],
    )
    title: str | None = Field(
        default=None,
        description="The trial's brief title, exactly as in the API (protocolSection.identificationModule.briefTitle).",
    )


# --- Encoding: field -> visual channel (Vega-Lite vocabulary) -----------------


class _VegaLiteNames(BaseModel):
    """Accepts and emits Vega-Lite's camelCase names (xOffset, timeUnit)."""

    model_config = ConfigDict(validate_by_name=True, validate_by_alias=True, serialize_by_alias=True)

    @model_serializer(mode="wrap")
    def _drop_empty(self, handler):
        """Leave unset channel options out of the output instead of sending nulls to the frontend."""
        return {k: v for k, v in handler(self).items() if v is not None}


class FieldType(str, Enum):
    """Vega-Lite measurement types: how the frontend should treat a field's values."""

    QUANTITATIVE = "quantitative"  # numbers: counts, enrollment
    NOMINAL = "nominal"  # unordered categories: sponsor, country
    ORDINAL = "ordinal"  # ordered categories: phase
    TEMPORAL = "temporal"  # dates, sent as ISO strings ("2015-01-01")


Aggregate = Literal["count", "sum", "mean", "median", "min", "max", "distinct"]
TimeUnit = Literal["year", "yearquarter", "yearmonth", "utcyear", "utcyearquarter", "utcyearmonth"]
Sort = Literal["ascending", "descending", "x", "-x", "y", "-y"] | list[str]


class Channel(_VegaLiteNames):
    field: str = Field(description="Key in each data row.")
    type: FieldType
    title: str | None = Field(default=None, description="Axis or legend label.")
    sort: Sort | None = Field(
        default=None,
        description="'-y' = order bars by value, largest first; a list = explicit order, e.g. phases.",
    )
    aggregate: Aggregate | None = Field(
        default=None,
        description="Usually unset: data arrives pre-aggregated. Set only if the frontend should aggregate.",
    )
    time_unit: TimeUnit | None = Field(default=None, alias="timeUnit", description="Prefer utc* units.")
    bin: bool | Literal["binned"] | None = Field(
        default=None, description="'binned' = rows are already bins; give the bin end in encoding.x2."
    )
    labels: dict[str, str] | None = Field(
        default=None,
        description="Display name for each coded value in this field (e.g. PHASE1 -> 'Phase 1'). "
        "Rows keep the codes; show the label when present, else the value as is.",
    )


class SecondaryChannel(_VegaLiteNames):
    """End of a range (e.g. bin end); takes its type from the matching primary channel."""

    field: str
    title: str | None = None


class ChartEncoding(_VegaLiteNames):
    x: Channel
    y: Channel
    x2: SecondaryChannel | None = Field(default=None, description="Bin end for pre-binned histograms.")
    color: Channel | None = Field(default=None, description="Splits data into colored groups.")
    x_offset: Channel | None = Field(
        default=None, alias="xOffset", description="Places grouped bars side by side within each x."
    )

    def fields(self) -> set[str]:
        channels = [self.x, self.y, self.x2, self.color, self.x_offset]
        return {c.field for c in channels if c is not None}


class NetworkEncoding(BaseModel):
    node_label: str = Field(default="label", description="Node key shown as its label.")
    node_group: str | None = Field(default="group", description="Node key used for color, e.g. 'drug' vs 'sponsor'.")
    node_size: str | None = Field(default="size", description="Node key used for size.")
    edge_weight: str | None = Field(default="weight", description="Edge key used for thickness.")
    group_labels: dict[str, str] | None = Field(
        default=None, description="Display name for each node group, e.g. lead_sponsor -> 'Lead sponsor'."
    )


# --- Data ---------------------------------------------------------------------


class DataRow(BaseModel):
    """One chart datum. Its keys are whatever the encoding names, plus citations."""

    model_config = ConfigDict(extra="allow")

    citations: list[Citation] = Field(default_factory=list)
    nct_ids: list[str] = Field(
        default_factory=list,
        description="Every trial counted in this data point (complete, sorted); `citations` detail the first few.",
    )


class Node(BaseModel):
    id: str
    label: str
    group: str | None = None
    size: float | None = None
    citations: list[Citation] = Field(default_factory=list)
    nct_ids: list[str] = Field(
        default_factory=list,
        description="Every trial counted in this data point (complete, sorted); `citations` detail the first few.",
    )


class Edge(BaseModel):
    source: str = Field(description="Node id.")
    target: str = Field(description="Node id.")
    weight: float = 1.0
    citations: list[Citation] = Field(default_factory=list)
    nct_ids: list[str] = Field(
        default_factory=list,
        description="Every trial counted in this data point (complete, sorted); `citations` detail the first few.",
    )


class NetworkData(BaseModel):
    """NetworkX node-link format: `networkx.node_link_graph(data, edges="edges")` reads it as is."""

    directed: bool = False
    multigraph: bool = False
    graph: dict[str, Any] = Field(default_factory=dict, description="Graph-level attributes.")
    nodes: list[Node]
    edges: list[Edge]

    @model_validator(mode="after")
    def edges_point_to_known_nodes(self) -> "NetworkData":
        ids = {n.id for n in self.nodes}
        dangling = [e for e in self.edges if e.source not in ids or e.target not in ids]
        if dangling:
            raise ValueError(f"{len(dangling)} edge(s) reference unknown node ids")
        return self


# --- Visualizations -------------------------------------------------------------


class ChartVisualization(BaseModel):
    type: ChartType
    intent: Intent = Field(description="What the chart shows (FT Visual Vocabulary category).")
    title: str
    encoding: ChartEncoding
    data: list[DataRow]

    @model_validator(mode="after")
    def check_consistency(self) -> "ChartVisualization":
        needed = self.encoding.fields()
        for i, row in enumerate(self.data):
            missing = needed - set(row.model_extra or {})
            if missing:
                raise ValueError(f"data[{i}] is missing encoded field(s): {sorted(missing)}")

        enc = self.encoding
        if self.type == "grouped_bar_chart" and (enc.color is None or enc.x_offset is None):
            raise ValueError("grouped_bar_chart requires encoding.color and encoding.xOffset")
        if self.type == "stacked_bar_chart" and enc.color is None:
            raise ValueError("stacked_bar_chart requires encoding.color")
        if self.type == "histogram":
            # Either numeric bins (x.bin) or pre-binned ranges given as ordered labels (ordinal x),
            # which suits skewed data whose bin widths grow geometrically.
            if not enc.x.bin and enc.x.type != FieldType.ORDINAL:
                raise ValueError("histogram requires encoding.x.bin or an ordinal x of ordered bin labels")
            if enc.x.bin == "binned" and enc.x2 is None:
                raise ValueError("pre-binned histogram requires encoding.x2 (bin end)")
        if self.type == "time_series" and enc.x.type not in (FieldType.TEMPORAL, FieldType.ORDINAL):
            raise ValueError("time_series requires a temporal or ordinal x")
        if self.type == "scatter_plot" and FieldType.QUANTITATIVE not in (enc.x.type, enc.y.type):
            raise ValueError("scatter_plot requires at least one quantitative axis")
        return self


class NetworkVisualization(BaseModel):
    type: Literal["network_graph"]
    intent: Literal[Intent.RELATIONSHIP] = Intent.RELATIONSHIP
    title: str
    encoding: NetworkEncoding = Field(default_factory=NetworkEncoding)
    data: NetworkData


Visualization = ChartVisualization | NetworkVisualization


# --- Metadata --------------------------------------------------------------------


class RunMetrics(BaseModel):
    """How the run went: time, cost and agent behaviour. The full trace is in trace.json."""

    seconds_total: float = Field(description="Agent run plus building the chart.")
    seconds_fetching: float = Field(
        description="Sum of fetch_data call durations (ClinicalTrials.gov API); fetches that ran in parallel each count."
    )
    seconds_building: float = Field(description="Building the visualization from the fetched trials.")
    model_turns: int
    input_tokens: int
    output_tokens: int
    tool_calls: dict[str, int] = Field(description="Calls per tool, incl. the final-answer tool.")
    sent_back: int = Field(description="Tool calls or answers code rejected and sent back to the model.")
    fetches: int
    failed_fetches: int


class ChainStep(BaseModel):
    """One fetch_data call the agent made, in order. Lets a reader check intermediate findings."""

    fetch: int = Field(ge=1, description="1 for the first fetch, 2 for the second, ...")
    rationale: str = Field(description="Why the agent made this fetch, in its words.")
    searches: list[dict[str, Any]] = Field(description="Exact API calls as executed: label, endpoint, params.")
    status: Literal["ok", "failed"]
    total_trials_matched: int | None = None
    error: str | None = None
    charted: bool = Field(default=False, description="True for the fetch whose data the chart is built from.")
    output_dir: str | None = Field(default=None, description="Folder with this fetch's plan, profile and data.")


class Meta(BaseModel):
    source: Literal["clinicaltrials.gov"] = "clinicaltrials.gov"
    interpretation: str = Field(description="Plain-English restatement of what was computed.")
    request_filters: dict[str, Any] = Field(
        default_factory=dict, description="The structured fields the user sent, exactly as sent (empty if none)."
    )
    filters_applied: dict[str, Any] = Field(
        default_factory=dict, description="Filters actually sent to the API (from the request and the question)."
    )
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list, description="E.g. results truncated, missing dates excluded.")
    total_trials_matched: int = Field(ge=0, description="Trials matching the filters at the source.")
    trials_analyzed: int = Field(ge=0, description="Trials actually aggregated (can be lower if capped).")
    units: dict[str, str] = Field(default_factory=dict, description="Field -> unit, e.g. {'trial_count': 'trials'}.")
    data_as_of: datetime | None = Field(default=None, description="When ClinicalTrials.gov last refreshed the data used.")
    api_version: str | None = Field(default=None, description="ClinicalTrials.gov API version that served the data.")
    chain: list[ChainStep] = Field(default_factory=list, description="Every fetch the agent made, in order.")
    metrics: RunMetrics | None = Field(default=None, description="Time, tokens and tool calls of this run.")
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# --- Top level ---------------------------------------------------------------------


class QueryResponse(BaseModel):
    """Successful response body for POST /query."""

    visualization: Visualization = Field(discriminator="type")
    meta: Meta

    @computed_field(description="Vega-Lite v5 spec for charts (render with vega-embed); null for network graphs.")
    @property
    def vega_lite(self) -> dict[str, Any] | None:
        from cheiron.visualize.vega_lite import to_vega_lite  # local import: visualize depends on models

        if isinstance(self.visualization, ChartVisualization):
            return to_vega_lite(self.visualization)
        return None


class ErrorResponse(BaseModel):
    """Error response body, e.g. 400 for a question we cannot answer."""

    error: Literal["invalid_request", "unsupported_query", "no_results", "upstream_error", "internal_error"]
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
