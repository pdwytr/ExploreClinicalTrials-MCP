"""Which chart answers which kind of question.

Intents follow the Financial Times Visual Vocabulary, which groups chart types by
the relationship in the data a reader should see:
https://github.com/Financial-Times/chart-doctor/tree/main/visual-vocabulary

The planner picks an *intent* from the question; this table then limits which
chart types may be used. The first chart type listed is the default.
"""

from enum import Enum
from typing import Literal

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
    CHANGE_OVER_TIME = "change_over_time"  # "How has X changed per year since 2015?"
    RANKING = "ranking"  # "Which countries have the most recruiting trials?"
    DISTRIBUTION = "distribution"  # "How are trials distributed across phases / enrollment sizes?"
    MAGNITUDE = "magnitude"  # "Compare phases for Drug A vs Drug B."
    PART_TO_WHOLE = "part_to_whole"  # "What share of trials is industry-sponsored?"
    CORRELATION = "correlation"  # "Does enrollment grow with trial duration?"
    SPATIAL = "spatial"  # "Where are trials located?"
    RELATIONSHIP = "relationship"  # "Show a network of sponsors <-> drugs."


INTENT_CHART_TYPES: dict[Intent, tuple[VisualizationType, ...]] = {
    Intent.CHANGE_OVER_TIME: ("time_series", "bar_chart", "grouped_bar_chart", "stacked_bar_chart"),
    Intent.RANKING: ("bar_chart",),
    Intent.DISTRIBUTION: ("bar_chart", "histogram"),
    Intent.MAGNITUDE: ("bar_chart", "grouped_bar_chart"),
    Intent.PART_TO_WHOLE: ("stacked_bar_chart", "bar_chart"),
    Intent.CORRELATION: ("scatter_plot",),
    Intent.SPATIAL: ("bar_chart",),  # a choropleth map could be added later
    Intent.RELATIONSHIP: ("network_graph",),
}


def default_chart_type(intent: Intent) -> VisualizationType:
    return INTENT_CHART_TYPES[intent][0]
