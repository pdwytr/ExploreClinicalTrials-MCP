"""Example user requests, one or two per kind of question.

Each case says what the system *should* do with the request: which intent the
question has and which chart answers it. Today the tests only check that the
request is valid and the chart fits the intent; once the planner exists, the same
cases check that it picks this intent and chart.

Question wording follows the brief's appendix (time trends, distributions,
comparisons, geographic patterns, relationships), mapped to FT intents.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Case:
    name: str
    request: dict
    intent: str
    chart: str


VALID_CASES = [
    # --- Change over time -------------------------------------------------------
    Case(
        "brief_example",
        {"query": "How has the number of trials for this drug changed over time?", "drug_name": "Pembrolizumab"},
        "change_over_time",
        "time_series",
    ),
    Case(
        "drug_per_year_since",
        {"query": "How has the number of trials for pembrolizumab changed per year since 2015?"},
        "change_over_time",
        "time_series",
    ),
    Case(
        "condition_starts_per_year_with_range",
        {"query": "How many trials started each year?", "condition": "Alzheimer's disease", "start_year": 2010, "end_year": 2024},
        "change_over_time",
        "time_series",
    ),
    # --- Distribution -----------------------------------------------------------
    Case(
        "condition_across_phases",
        {"query": "How are breast cancer trials distributed across phases?"},
        "distribution",
        "bar_chart",
    ),
    Case(
        "enrollment_size_distribution",
        {"query": "What is the distribution of enrollment sizes?", "condition": "type 2 diabetes"},
        "distribution",
        "histogram",
    ),
    # --- Ranking ----------------------------------------------------------------
    Case(
        "common_intervention_types",  # the brief lists this under distributions; "most common" reads as a ranking
        {"query": "What are the most common intervention types for melanoma trials?"},
        "ranking",
        "bar_chart",
    ),
    Case(
        "top_sponsors_filtered_by_phase",
        {"query": "Who are the top 10 sponsors?", "condition": "obesity", "trial_phase": ["PHASE3"]},
        "ranking",
        "bar_chart",
    ),
    # --- Magnitude (comparisons) ------------------------------------------------
    Case(
        "drug_a_vs_drug_b_phases",
        {"query": "Compare phases for trials involving nivolumab vs pembrolizumab."},
        "magnitude",
        "grouped_bar_chart",
    ),
    Case(
        "sponsor_types_two_conditions",
        {"query": "Compare sponsor categories across asthma and COPD trials."},
        "magnitude",
        "grouped_bar_chart",
    ),
    # --- Part to whole ----------------------------------------------------------
    Case(
        "industry_share_by_phase",
        {"query": "What share of lung cancer trials in each phase is industry-sponsored?"},
        "part_to_whole",
        "stacked_bar_chart",
    ),
    # --- Correlation ------------------------------------------------------------
    Case(
        "enrollment_vs_duration",
        {"query": "Do larger trials run longer?", "condition": "oncology", "trial_phase": ["PHASE3"]},
        "correlation",
        "scatter_plot",
    ),
    # --- Spatial ----------------------------------------------------------------
    Case(
        "countries_recruiting",
        {"query": "Which countries have the most recruiting trials for multiple sclerosis?", "recruitment_status": ["RECRUITING"]},
        "spatial",
        "bar_chart",
    ),
    # --- Relationship (networks) ------------------------------------------------
    Case(
        "sponsor_drug_network",
        {"query": "Show a network of sponsors and drugs for Hodgkin lymphoma trials."},
        "relationship",
        "network_graph",
    ),
    Case(
        "drug_combination_network",
        {"query": "Which drugs frequently co-occur in combination studies?", "condition": "colorectal cancer"},
        "relationship",
        "network_graph",
    ),
    # --- Every structured field at once -----------------------------------------
    Case(
        "all_filters",
        {
            "query": "How many trials started per year?",
            "drug_name": "Semaglutide",
            "condition": "obesity",
            "trial_phase": ["PHASE2", "PHASE3"],
            "sponsor": "Novo Nordisk A/S",
            "country": "United States",
            "recruitment_status": ["COMPLETED", "RECRUITING"],
            "start_year": 2015,
            "end_year": 2025,
        },
        "change_over_time",
        "time_series",
    ),
]


# Requests that must be rejected: (name, request, field the error should point at).
INVALID_CASES = [
    ("missing_query", {"drug_name": "Pembrolizumab"}, "query"),
    ("empty_query", {"query": ""}, "query"),
    ("whitespace_query", {"query": "    "}, "query"),
    ("query_too_long", {"query": "x" * 501}, "query"),
    ("unknown_field", {"query": "trials by phase", "drugname": "Pembrolizumab"}, "drugname"),
    ("empty_drug_name", {"query": "trials by phase", "drug_name": ""}, "drug_name"),
    ("unknown_phase", {"query": "trials", "trial_phase": ["PHASE9"]}, "trial_phase"),
    ("phase_not_a_list", {"query": "trials", "trial_phase": "PHASE3"}, "trial_phase"),
    ("empty_phase_list", {"query": "trials", "trial_phase": []}, "trial_phase"),
    ("unknown_status", {"query": "trials", "recruitment_status": ["OPEN"]}, "recruitment_status"),
    ("year_not_a_number", {"query": "trials", "start_year": "last year"}, "start_year"),
    ("year_out_of_range", {"query": "trials", "start_year": 1800}, "start_year"),
    ("years_reversed", {"query": "trials per year", "start_year": 2020, "end_year": 2015}, None),  # whole-request check
]
