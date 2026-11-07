"""Translate our chart spec into a Vega-Lite v5 spec.

Deterministic, no AI: the same ChartVisualization always gives the same spec.
Docs: https://vega.github.io/vega-lite/docs/
"""

from typing import Any

from cheiron.models.response import Channel, ChartVisualization

SCHEMA = "https://vega.github.io/schema/vega-lite/v5.json"

MARKS: dict[str, Any] = {
    "bar_chart": "bar",
    "grouped_bar_chart": "bar",
    "stacked_bar_chart": "bar",
    "histogram": "bar",
    "time_series": {"type": "line", "point": True},
    "scatter_plot": "point",
}


def _channel(channel: Channel) -> dict[str, Any]:
    return channel.model_dump(by_alias=True, exclude_none=True, mode="json")


def to_vega_lite(viz: ChartVisualization) -> dict[str, Any]:
    enc = viz.encoding
    encoding: dict[str, Any] = {"x": _channel(enc.x), "y": _channel(enc.y)}
    if enc.x2 is not None:
        encoding["x2"] = enc.x2.model_dump(exclude_none=True)
    if enc.color is not None:
        encoding["color"] = _channel(enc.color)
    if enc.x_offset is not None:
        encoding["xOffset"] = _channel(enc.x_offset)

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
        "data": {"values": [row.model_dump(mode="json") for row in viz.data]},  # citations ride along
        "mark": MARKS[viz.type],
        "encoding": encoding,
    }
