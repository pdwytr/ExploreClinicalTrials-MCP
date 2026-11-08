# Worked examples

Each example gives a question, what to look for in the profile, and the plan. The examples teach
the shape of a choice; the drugs and conditions in them are arbitrary.

## Trend for one search

"Has atezolizumab trial activity grown year by year since 2018?" The search covered start dates
from 2018, so count by `start_year`.
```json
{"intent": "change_over_time", "chart_type": "time_series", "title": "Atezolizumab trials started per year since 2018", "x": "start_year"}
```

## Completed, not started

"How many glioblastoma studies finished in each year from 2012?" The period is about completion
dates, so `x: completion_year` (counting by start year would be rejected).
```json
{"intent": "change_over_time", "chart_type": "time_series", "title": "Glioblastoma trials completed per year since 2012", "x": "completion_year"}
```

## Ranking with a number

"Top 10 countries hosting endometriosis studies that are enrolling now" asks for a number, so
`top_n: 10`. Without a number, a readable cut such as 15 is fine.
```json
{"intent": "ranking", "chart_type": "bar_chart", "title": "Top 10 countries for enrolling endometriosis studies", "x": "country", "top_n": 10}
```

## Named values

"For gout, how do active, withdrawn and suspended trials compare?" The question names three
statuses: leave `top_n` unset so none of them is dropped for a larger, unnamed status.
```json
{"intent": "magnitude", "chart_type": "bar_chart", "title": "Gout trials by status: active, withdrawn and suspended", "x": "overall_status"}
```

## Comparing two conditions

"Industry, academic or government: who funds epilepsy research versus schizophrenia research?" Two
steps were fetched, so the sides go on `series: group`.
```json
{"intent": "magnitude", "chart_type": "grouped_bar_chart", "title": "Sponsor types in epilepsy vs schizophrenia trials", "x": "sponsor_class", "series": "group"}
```

## A tie at the top

"Which organisation leads the most lupus studies?" The profile's `lead_sponsor` shows
`tied_for_top` with two sponsors: show the leaders, not one of them.
```json
{"intent": "ranking", "chart_type": "bar_chart", "title": "Sponsors with the most lupus trials (tie for first)", "x": "lead_sponsor", "top_n": 10}
```

## Multi-step question

"Take whoever runs the most tuberculosis trials: what does their trial activity look like over
time?" The first fetch found the sponsor; the latest fetch holds that sponsor's trials, so chart it
as a trend.
```json
{"intent": "change_over_time", "chart_type": "time_series", "title": "Trials per year for the leading tuberculosis sponsor", "x": "start_year"}
```
