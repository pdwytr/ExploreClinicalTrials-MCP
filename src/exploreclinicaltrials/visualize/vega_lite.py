"""Translate our chart spec into a Vega-Lite v5 spec.

Deterministic, no AI: the same ChartVisualization always gives the same spec.
Docs: https://vega.github.io/vega-lite/docs/
"""

import json
from typing import Any

from exploreclinicaltrials.models.response import Channel, ChartVisualization

SCHEMA = "https://vega.github.io/schema/vega-lite/v5.json"

MARKS: dict[str, Any] = {
    "bar_chart": "bar",
    "grouped_bar_chart": "bar",
    "stacked_bar_chart": "bar",
    "histogram": "bar",
    "time_series": {"type": "line", "point": True},
    "scatter_plot": "point",
}


def _channel(channel: Channel, guide: str | None = "axis") -> dict[str, Any]:
    """A Vega-Lite channel. `labels` is ours, not Vega-Lite's: it becomes a labelExpr on the
    channel's axis or legend, so the chart shows display names while the data keeps the codes."""
    spec = channel.model_dump(by_alias=True, exclude_none=True, mode="json", exclude={"labels", "scale"})
    if channel.scale:
        spec["scale"] = {"type": channel.scale}
    if channel.labels and guide:  # xOffset has no axis or legend of its own
        lookup = json.dumps(channel.labels, ensure_ascii=False)
        spec[guide] = {"labelExpr": f"{lookup}[datum.label] || datum.label"}
    return spec


def to_vega_lite(viz: ChartVisualization) -> dict[str, Any]:
    enc = viz.encoding
    encoding: dict[str, Any] = {"x": _channel(enc.x), "y": _channel(enc.y)}
    if enc.x2 is not None:
        encoding["x2"] = enc.x2.model_dump(exclude_none=True)
    if enc.color is not None:
        encoding["color"] = _channel(enc.color, "legend")
    if enc.x_offset is not None:
        encoding["xOffset"] = _channel(enc.x_offset, None)

    if viz.type == "stacked_bar_chart":
        encoding["y"]["stack"] = "zero"
    elif viz.type == "grouped_bar_chart":
        encoding["y"]["stack"] = None  # side by side, not stacked

    encoding["tooltip"] = [
        {"field": c.field, "type": c.type.value} for c in (enc.x, enc.y, enc.color) if c is not None
    ]

    return {
        "$schema": SCHEMA,
        "title": viz.title,
        "width": "container",
        # values only, plus _row (the index into visualization.data, where each row's citations and
        # nct_ids are): sending the sources twice doubled responses (a 2,000-point scatter: 3.8 MB)
        "data": {
            "values": [
                row.model_dump(mode="json", exclude={"nct_ids", "citations"}) | {"_row": i} for i, row in enumerate(viz.data)
            ]
        },
        "mark": MARKS[viz.type],
        "encoding": encoding,
    }
