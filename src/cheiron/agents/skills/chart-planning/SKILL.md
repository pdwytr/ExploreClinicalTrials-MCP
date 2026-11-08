---
name: chart-planning
description: >-
  Use this skill when the data for a clinical-trials question has been fetched and profiled with
  describe_data and you must choose the chart that answers it: the chart type, the field on x and on
  the series, how many categories to keep, and a title, written as the ChartPlan that code turns into
  a visualization. Use it for trends over time, rankings, distributions, comparisons between drugs,
  conditions or sponsors, geography, and relationships between sponsors, drugs and conditions, even
  when the question never says "chart" or "plot".
metadata:
  version: "2"
  output: "ChartPlan: one visualization per question"
---

# Choosing the chart

You see a **profile** of the fetched data, never the records. Code draws the chart from your plan:
it counts **distinct trials** per value and attaches citations. You never compute or write numbers,
including in the title. Code checks every plan against the profile; a plan that does not fit comes
back with the reason, so fix the plan and answer again.

## Procedure

1. **Read the profile.** Per field: `distinct` values, `missing` trials, `top_values` (with trial
   counts), `multi_valued` (a trial can have several values), `missing_by_group` per comparison side,
   and for enrollment `numeric` min/median/max. `group_sizes` lists the comparison sides; fields
   marked `from_registry_stats` came from registry-wide statistics.
2. **Classify the question** and start from its row in the default table below. Leave the default
   only when a Gotcha says so.
3. **Pick the fields.** `x` is the field the question is about; `series` is the comparison side
   (`group`) or a second breakdown. Skip a field missing for most trials: code warns above 10%
   missing and refuses a field no trial has.
4. **Set `top_n`** only when the question asks for a number of items ("top 10 sponsors").
5. **Write the title**: what is shown, in the question's words, with no numbers.
6. **Check the plan against the Gotchas**, then answer with it.

## Default chart per question

| The question asks for | Example wording | `intent` | Default plan |
| --- | --- | --- | --- |
| Change over time | "per year since 2015", "completed each year" | `change_over_time` | `time_series`, `x: start_year` (or `completion_year`) |
| A ranking | "which countries have the most", "top sponsors" | `ranking` | `bar_chart`, `x` = that field, `top_n` if a number is asked |
| Spread across categories | "distributed across phases", "intervention types" | `distribution` | `bar_chart`, `x` = that field |
| Spread of a number | "enrollment sizes" | `distribution` | `histogram`, `x: enrollment` |
| Sides compared | "A vs B by phase", "across two conditions" | `magnitude` | `grouped_bar_chart`, `x` = field, `series: group` |
| Parts of a whole | "what part of each status is industry-run" | `part_to_whole` | `stacked_bar_chart`, `x` + single-valued `series` |
| A share or percentage | "what percentage are …", "what share of each …" | `part_to_whole` | the same chart with `measure: "share"` (see Gotchas) |
| Where trials run | "by country" | `spatial` | `bar_chart`, `x: country` |
| Links between things | "sponsors and their drugs", "drugs used together" | `relationship` | `network_graph`: read `references/networks.md` |

Profile has fields marked `from_registry_stats`: read `references/registry-stats.md` first.

## Fields you can chart

`phase`, `start_year`, `completion_year`, `overall_status`, `lead_sponsor`, `sponsor_class`, `condition`,
`intervention`, `intervention_type`, `country`, `enrollment` (numeric), `study_type`, `allocation`
(randomized or not), `masking` (blinding: none = open label, single ... quadruple), `primary_purpose`,
and `group` (the comparison side: the label of each fetched step). Design fields are mostly empty for
observational studies.

## Output

A ChartPlan: `intent`, `chart_type`, `title` (at most 120 characters), `x`, and optionally `series`,
`top_n` (1–50) and `measure` (`count`, the default, or `share`). For a comparison of two fetched sides by phase:

```json
{"intent": "magnitude", "chart_type": "grouped_bar_chart", "title": "Trial phases: durvalumab vs atezolizumab", "x": "phase", "series": "group"}
```

## Gotchas

- **Comparisons must show every side.** When several steps were fetched (`group_sizes` has more
  than one side), use `series: group` (or `x: group`). With one search, `group` is rejected.
- **Never stack a multi-valued field** (phase, condition, intervention, intervention_type, country).
  A trial counts once per value, so the parts would not add up; grouped bars are fine.
- **Named values must all be visible.** If the question names the values it wants ("recruiting vs
  completed vs terminated"), leave `top_n` unset: code keeps only the largest categories, and a small
  `top_n` silently drops a named value in favour of an unnamed one.
- **Many categories:** code shows at most 25, largest first. Set `top_n` lower for rankings; leave
  it unset for phases and years, which code orders (phases clinically, years continuously with empty
  years as 0, stopping at the data date).
- **Started vs completed:** "trials completed each year" needs `completion_year`. A time series must
  count by the same date as the searched period, or it is rejected.
- **A time series needs at least 2 years with data**; with one year use a `bar_chart`.
- **Few trials:** under 10 trials code adds a warning; say "few trials" in the title of a ranking or
  trend.
- **Ties:** when the profile shows `tied_for_top`, the chart and title show every tied value, never
  one presented as the leader.
- **Shares:** when the question asks for a percentage, share or proportion, set `measure: "share"`;
  code computes the percentages, never you. The denominator follows from the chart: no series =
  share of all charted trials; with a series = share within each x category ("in each phase, what
  share is industry-run": `x: phase`, `series: sponsor_class`); `series: group` = share within each
  compared side. Bars and time series only; not registry-wide statistics.
- **Numbers:** `enrollment` is the only numeric field, so it is charted only as a `histogram`, and
  `scatter_plot` is not available (it needs two numeric fields per trial). `x` and `series` must
  differ except in a network.

## References

Read a file only when its row applies: `read_reference(skill="chart-planning", path="<file>")`.

| File | Read when |
| --- | --- |
| `references/networks.md` | The question is about links between sponsors, drugs, conditions or countries |
| `references/registry-stats.md` | The profile has fields marked `from_registry_stats` |
| `references/chart-types.md` | A plan was rejected and you need each chart type's exact requirements, or you are unsure between grouped and stacked bars |
| `references/examples.md` | The question fits no row of the default table, or you want a worked example for ties, completion years, multi-step questions or rankings |
