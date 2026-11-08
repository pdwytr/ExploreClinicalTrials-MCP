# Chart types: what each needs

Code rejects a plan that breaks a rule below and sends back the reason.

| `chart_type` | Shows | Needs |
| --- | --- | --- |
| `bar_chart` | Trials per category | `x` = a category field; no `series` |
| `grouped_bar_chart` | Categories side by side per series value | `x` + `series`, different fields; `series: group` for comparisons |
| `stacked_bar_chart` | Parts of a whole per category | `x` + `series`; **neither multi-valued** |
| `time_series` | Trials per year | `x: start_year` or `completion_year`, the same date the search period used; at least 2 years with data; optional `series` |
| `histogram` | Spread of enrollment | `x: enrollment`, no `series`. Code bins it into ordered ranges ("0–49" … "10,000+") |
| `network_graph` | Values that share trials | `x` and `series` = the node kinds, may be the same field (see `networks.md`) |
| `scatter_plot` | — | Not available: only one numeric field (enrollment) exists per trial |

## Rules for every plan

- `group` (the comparison side) is allowed only when several steps were fetched.
- A field with no value in any fetched trial is rejected; above 10% missing, code warns and leaves
  those trials out.
- `enrollment` is numeric: only in a `histogram`.
- `x` and `series` must differ, except in a `network_graph`.
- `top_n` is 1–50; without it code shows at most 25 categories, largest first.
- Registry-wide statistics allow only a one-field `bar_chart` (see `registry-stats.md`).

## Grouped or stacked?

Use **grouped** to compare sizes across series values (most comparisons, and anything multi-valued).
Use **stacked** only when the question is about shares of a whole and the series is single-valued
(`sponsor_class`, `overall_status`, `lead_sponsor`, years, `group`).

Example: share of industry-sponsored trials in each phase. Phase is multi-valued, so it can be on
`x` but the series must be single-valued:
```json
{"intent": "part_to_whole", "chart_type": "stacked_bar_chart", "title": "Lung cancer trials per phase by sponsor type", "x": "phase", "series": "sponsor_class"}
```
