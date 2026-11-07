"""What we send back: a visualization spec a frontend can render without guessing.

Shape:
    QueryResponse
    ├── visualization   ChartVisualization | NetworkVisualization  (picked by `type`)
    │   ├── type, title
    │   ├── encoding    which data field goes on which visual channel
    │   └── data        the rows (charts) or nodes + edges (network)
    │                   every row / node / edge may carry `citations`
    └── meta            filters, interpretation, rendering hints, counts
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


# --- Encoding: field -> visual channel ---------------------------------------


class FieldType(str, Enum):
    """How the frontend should treat a field's values (same idea as Vega-Lite)."""

    QUANTITATIVE = "quantitative"  # numbers: counts, enrollment
    NOMINAL = "nominal"  # unordered categories: sponsor, country
    ORDINAL = "ordinal"  # ordered categories: phase
    TEMPORAL = "temporal"  # dates / years


class Channel(BaseModel):
    field: str = Field(description="Key in each data row.")
    type: FieldType
    title: str | None = Field(default=None, description="Axis or legend label.")


class ChartEncoding(BaseModel):
    x: Channel
    y: Channel
    series: Channel | None = Field(
        default=None, description="Splits data into colored groups (grouped bars, multi-line series)."
    )


class NetworkEncoding(BaseModel):
    node_label: str = Field(default="label", description="Node key shown as its label.")
    node_group: str | None = Field(default="group", description="Node key used for color, e.g. 'drug' vs 'sponsor'.")
    node_size: str | None = Field(default="size", description="Node key used for size.")
    edge_weight: str | None = Field(default="weight", description="Edge key used for thickness.")


# --- Data ---------------------------------------------------------------------


class DataRow(BaseModel):
    """One chart datum. Its keys are whatever the encoding names, plus citations."""

    model_config = ConfigDict(extra="allow")

    citations: list[Citation] = Field(default_factory=list)


class Node(BaseModel):
    id: str
    label: str
    group: str | None = None
    size: float | None = None
    citations: list[Citation] = Field(default_factory=list)


class Edge(BaseModel):
    source: str = Field(description="Node id.")
    target: str = Field(description="Node id.")
    weight: float = 1.0
    citations: list[Citation] = Field(default_factory=list)


class NetworkData(BaseModel):
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
    type: Literal["bar_chart", "grouped_bar_chart", "time_series", "scatter_plot", "histogram"]
    title: str
    encoding: ChartEncoding
    data: list[DataRow]

    @model_validator(mode="after")
    def encoded_fields_exist_in_data(self) -> "ChartVisualization":
        """Every field the encoding names must be present in every row."""
        channels = [self.encoding.x, self.encoding.y, self.encoding.series]
        needed = {c.field for c in channels if c is not None}
        for i, row in enumerate(self.data):
            missing = needed - set(row.model_extra or {})
            if missing:
                raise ValueError(f"data[{i}] is missing encoded field(s): {sorted(missing)}")
        if self.type == "grouped_bar_chart" and self.encoding.series is None:
            raise ValueError("grouped_bar_chart requires encoding.series")
        return self


class NetworkVisualization(BaseModel):
    type: Literal["network_graph"]
    title: str
    encoding: NetworkEncoding = Field(default_factory=NetworkEncoding)
    data: NetworkData


Visualization = ChartVisualization | NetworkVisualization


# --- Metadata --------------------------------------------------------------------


class Sort(BaseModel):
    field: str
    order: Literal["asc", "desc"] = "desc"


class Meta(BaseModel):
    source: Literal["clinicaltrials.gov"] = "clinicaltrials.gov"
    interpretation: str = Field(description="Plain-English restatement of what was computed.")
    filters_applied: dict[str, Any] = Field(
        default_factory=dict, description="Filters actually sent to the API (from the request and the question)."
    )
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list, description="E.g. results truncated, missing dates excluded.")
    total_trials_matched: int = Field(ge=0, description="Trials matching the filters at the source.")
    trials_analyzed: int = Field(ge=0, description="Trials actually aggregated (can be lower if capped).")
    sort: Sort | None = None
    time_granularity: Literal["year", "quarter", "month"] | None = None
    units: dict[str, str] = Field(default_factory=dict, description="Field -> unit, e.g. {'trial_count': 'trials'}.")
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# --- Top level ---------------------------------------------------------------------


class QueryResponse(BaseModel):
    """Successful response body for POST /query."""

    visualization: Visualization = Field(discriminator="type")
    meta: Meta


class ErrorResponse(BaseModel):
    """Error response body, e.g. 400 for a question we cannot answer."""

    error: Literal["invalid_request", "unsupported_query", "no_results", "upstream_error", "internal_error"]
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
