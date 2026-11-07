---
name: chart-planning
description: Chooses the chart that answers a clinical-trials question from a profile of the fetched data - chart type, which field goes on x and on the series, how many categories to show, and a title. Use after data has been fetched and described, to write the ChartPlan that code turns into a visualization.
metadata:
  answers: one visualization per question
---

# Choosing the chart

You see a **profile** of the fetched data (from `describe_data`), never the records.
Code draws the chart from your plan: it counts **distinct trials** per value and attaches
citations. You never compute or write numbers, including in the title.

## Read the profile first

For each field: `distinct` values, `missing` trials, `top_values` (with trial counts),
`multi_valued` (a trial can have several values), `missing_by_group` per comparison side,
and for enrollment `numeric` min/median/max. `group_sizes` lists the comparison sides.
Pick fields the question is about **and** the data supports: a field missing for most
trials gives a misleading chart (code warns above 10% missing, refuses at 100%).

## Fields you can chart

`phase`, `start_year`, `completion_year`, `overall_status`, `lead_sponsor`, `sponsor_class`, `condition`,
`intervention`, `intervention_type`, `country`, `enrollment` (numeric), and `group`
(the comparison side: the label of each fetched step).

## Chart types and what each needs

| `chart_type` | Use for | Needs (checked by code) |
| --- | --- | --- |
| `bar_chart` | Counts per category, rankings ("most common", "which countries") | `x` = a category field |
| `grouped_bar_chart` | Comparing sides or categories side by side ("A vs B by phase") | `x` + `series` (different fields; `series: group` for comparisons) |
| `stacked_bar_chart` | Parts of a whole ("share of industry trials per phase") | `x` + `series`; **neither may be multi-valued** (parts would not add up) |
| `time_series` | Change over time ("per year since 2015", "completed each year") | `x: start_year` or `completion_year`, matching the searched period's field; optional `series` |
| `histogram` | Spread of a number ("enrollment sizes") | `x: enrollment` |
| `network_graph` | Relationships ("sponsors <-> drugs", "drugs used together") | `x` and `series` = the two node kinds; the **same field twice** = co-occurrence within a trial |

`scatter_plot` is not available: only one numeric field (enrollment) exists per trial.

## Rules

- **Comparisons:** when several steps were fetched (`group_sizes` has several sides),
  the chart must show them: `series: group` (or `x: group`).
- **Multi-valued fields** (phase, condition, intervention, intervention_type, country) count
  a trial once per value, so bars can sum to more than the trials. Fine for bars and
  grouped bars; never stack them.
- **Many categories:** code shows at most 25 (largest first). Set `top_n` lower for
  rankings ("top 10 sponsors"); leave it unset for phases and years.
- **Phases** keep clinical order and **years** run continuously with empty years as 0.
  Year axes cover the searched period and stop at the data date (later dates are estimates
  for trials not started or finished yet): code handles all of this and notes it in meta.
- **Started vs completed:** "trials completed each year" needs `completion_year`; a chart
  counting by a different date than the search period is rejected.
- `intent` is a label for the reader: `change_over_time`, `ranking`, `distribution`,
  `magnitude`, `part_to_whole`, `correlation`, `spatial` or `relationship`.
- **Title:** says what is shown, in the question's terms, with no numbers.

## Examples

Comparison of two fetched sides by phase:
```json
{"intent": "magnitude", "chart_type": "grouped_bar_chart", "title": "Trial phases: nivolumab vs pembrolizumab", "x": "phase", "series": "group"}
```

Trend for one search:
```json
{"intent": "change_over_time", "chart_type": "time_series", "title": "Pembrolizumab trials started per year", "x": "start_year"}
```

Ranking:
```json
{"intent": "ranking", "chart_type": "bar_chart", "title": "Countries with the most recruiting multiple sclerosis trials", "x": "country", "top_n": 15}
```

Drugs used together:
```json
{"intent": "relationship", "chart_type": "network_graph", "title": "Drugs combined in colorectal cancer trials", "x": "intervention", "series": "intervention"}
```
