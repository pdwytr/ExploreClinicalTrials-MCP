# Worked examples

Each example gives the question, what to look for in the profile, and the plan.

## Trend for one search

"How has the number of trials for pembrolizumab changed per year since 2015?" The search covered
start dates from 2015, so count by `start_year`.
```json
{"intent": "change_over_time", "chart_type": "time_series", "title": "Pembrolizumab trials started per year since 2015", "x": "start_year"}
```

## Completed, not started

"How many breast cancer trials were completed each year since 2010?" The period is about completion
dates, so `x: completion_year` (counting by start year would be rejected).
```json
{"intent": "change_over_time", "chart_type": "time_series", "title": "Breast cancer trials completed per year since 2010", "x": "completion_year"}
```

## Ranking with a number

"Which countries have the most recruiting trials for multiple sclerosis?" No number is asked, so a
readable cut such as 15 is fine; "top 10" would mean `top_n: 10`.
```json
{"intent": "ranking", "chart_type": "bar_chart", "title": "Countries with the most recruiting multiple sclerosis trials", "x": "country", "top_n": 15}
```

## Named values

"How many cystic fibrosis trials are recruiting vs completed vs terminated?" The question names three
statuses: leave `top_n` unset so none of them is dropped for a larger, unnamed status.
```json
{"intent": "magnitude", "chart_type": "bar_chart", "title": "Cystic fibrosis trials: recruiting, completed and terminated", "x": "overall_status"}
```

## Comparing two conditions

"Compare sponsor categories across asthma and COPD trials." Two steps were fetched, so the sides go
on `series: group`.
```json
{"intent": "magnitude", "chart_type": "grouped_bar_chart", "title": "Sponsor categories in asthma vs COPD trials", "x": "sponsor_class", "series": "group"}
```

## A tie at the top

"Which sponsor runs the most ALS trials?" The profile's `lead_sponsor` shows `tied_for_top` with two
sponsors: show the leaders, not one of them.
```json
{"intent": "ranking", "chart_type": "bar_chart", "title": "Sponsors with the most ALS trials (tie for first)", "x": "lead_sponsor", "top_n": 10}
```

## Multi-step question

"For the sponsor with the most melanoma trials, how have its trials changed per year?" The first
fetch found the sponsor; the latest fetch holds that sponsor's trials, so chart it as a trend.
```json
{"intent": "change_over_time", "chart_type": "time_series", "title": "Trials per year for the leading melanoma sponsor", "x": "start_year"}
```
