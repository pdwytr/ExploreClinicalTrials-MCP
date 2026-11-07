---
name: ctgov-search
description: Turns a natural-language question about clinical trials into ClinicalTrials.gov API v2 calls - /studies searches (query.* and filter.* parameters, Essie syntax), single-study lookups, or registry-wide /stats. Use when planning which data to fetch to answer a question about drugs, conditions, sponsors, phases, locations, dates or trial counts.
metadata:
  api-version: "2.0.5"
  sources: docs/ctgov (official API snapshots)
---

# Planning ClinicalTrials.gov API calls

You choose the endpoint and write its parameters; code validates them, adds the
user's structured filters, runs the calls, and counts the results. You never compute numbers.

**Code handles all pagination, page sizes, result limits, field selection and
retries.** Never set `pageSize`, `pageToken`, `countTotal`, `fields` (on `studies`)
or `sort` (they are rejected). Write each search for the whole question, however many trials it matches.

## Procedure

1. Read the question and the user's structured filters. Choose the endpoint (next section).
   Almost every question is a `studies` search.
2. If the question compares named things (drug A vs drug B, condition X vs Y),
   write **one step per side**, each with a short label. Otherwise write one step.
3. For `studies`: put each concept in the parameter whose search area fits it (table below),
   and fixed-value constraints (phase, study type, sponsor class, dates, enrollment)
   in `filter.advanced` as `AREA[Field]...` expressions.
4. Write a one-sentence rationale saying what you fetched and any assumption made.
5. If trial registry records cannot answer the question, return `unanswerable`
   with the reason instead of a plan.

## Which endpoint

| Question is about | `endpoint` | You provide |
| --- | --- | --- |
| Any set of trials defined by a drug, condition, sponsor, place, phase, status or date | `studies` | `params` (search parameters) |
| One named trial ("NCT05064059") | `study` | `nct_id` |
| A fixed-value or text field across **all registered trials** ("how are all trials split by phase?") | `stats/field/values` | `fields`, e.g. `["Phase"]` |
| How many items a list field holds across all trials ("how many conditions does a trial list?") | `stats/field/sizes` | `fields`, e.g. `["Condition"]` |
| Study record sizes across the registry | `stats/size` | nothing |

Rules for the `stats/*` endpoints (checked against the live API):
- They cover the **whole registry and cannot filter**. If the question or the user's
  filters narrow the trials in any way, use `studies` instead (a stats step with user
  filters is rejected).
- `stats/field/values` gives counts only for **fixed-value fields** (complete, e.g. `Phase`,
  `OverallStatus`, `LeadSponsorClass`) and **text fields** (only the **top 250** values,
  e.g. `LeadSponsorName` has ~52,700). For dates and numbers (`StartDate`,
  `EnrollmentCount`) it returns only min/max/average, so "trials started per year" needs `studies`.

## Which parameter (`studies`)

| Concept | Parameter | Example value |
| --- | --- | --- |
| Disease / condition | `query.cond` | `"multiple sclerosis"` |
| Drug, biologic, device, procedure | `query.intr` | `"pembrolizumab"` |
| Sponsor or collaborator organisation | `query.spons` | `"Novo Nordisk"` |
| Lead sponsor only | `query.lead` | `"Pfizer"` |
| Country, state, city of a site | `query.locn` | `"Germany" OR "France"` |
| Anything else (keywords, acronyms) | `query.term` | `"CAR-T"` |
| Overall status | `filter.overallStatus` | `RECRUITING\|NOT_YET_RECRUITING` |
| Phase, type, dates, counts, classes | `filter.advanced` | `AREA[Phase](PHASE2 OR PHASE3)` |

## Essie essentials

- **Always quote multi-word terms**: `"multiple sclerosis"`. Unquoted terms use the
  default `Relaxation` expansion, which also matches the words apart
  (unquoted 3,957 trials vs quoted 3,729; the extra ones include tuberous sclerosis).
- Combine with `OR`, `AND`, `NOT`, and parentheses. Precedence: NOT > AND > OR, so
  parenthesise mixed expressions: `("asthma" OR "COPD") AND NOT "pediatric"`.
- Fixed values: `AREA[Phase]PHASE3`, `AREA[StudyType]INTERVENTIONAL`,
  `AREA[LeadSponsorClass]INDUSTRY`, `AREA[InterventionType]DEVICE`.
- Ranges (dates are YYYY-MM-DD; `MIN`/`MAX` for open ends):
  `AREA[StartDate]RANGE[2015-01-01,MAX]`, `AREA[EnrollmentCount]RANGE[1000,MAX]`.
  RANGE never matches trials with no value in that field.
- Same-site conditions need `SEARCH[Location](...)`:
  `SEARCH[Location](AREA[LocationCountry]United States AND AREA[LocationStatus]RECRUITING)`.
- Enum values are UPPER_SNAKE_CASE exactly as listed in references/enums.md.
- Search-only counters filter on list sizes, e.g. trials testing 2+ interventions:
  `AREA[NumInterventions]RANGE[2,MAX]`.

## Rules learned from the live API

- **Do not add synonyms or brand names** for a single drug: the API already matches
  them (`"Keytruda"` and `"pembrolizumab"` both return 3,003 trials).
- **Do expand drug classes into member drugs** and say so in the rationale:
  `"GLP-1 receptor agonist"` finds 350 trials, `"semaglutide" OR "liraglutide" OR "dulaglutide"` finds 1,378.
- **Expand regions into countries**: `query.locn="Europe"` matches facility names,
  not the continent.
- **"Trials" usually means interventional studies**; add `AREA[StudyType]INTERVENTIONAL`
  when the question is about testing treatments. Leave it out for "studies" in general.
- **"Ongoing"** = `NOT_YET_RECRUITING|RECRUITING|ENROLLING_BY_INVITATION|ACTIVE_NOT_RECRUITING`.
- **Years mean start date** unless the question says completed (`CompletionDate`) or
  posted (`StudyFirstPostDate`).
- **Combination therapy** = `AND` inside `query.intr`: `"pembrolizumab" AND "carboplatin"`.
- **Exclusions** = `NOT`: `"diabetes" NOT "type 1 diabetes"`.
- Do not narrow a question beyond what it asks just to get fewer results: large
  result sets are code's problem, not yours.

## Comparisons

One search per side, identical except for the compared concept, so the sides are
comparable. Comparing **attributes** of one set of trials (phase 2 vs phase 3,
industry vs academic, by year) is **one** search: the chart splits it later.

## User's structured filters

They are listed in the request. Include them in your searches. Code also adds any
you miss (AND-ed onto your parameters), so never contradict them.

## Feedback

If you receive feedback (API error message, "not found", "no trials matched", or a
stats step rejected because of user filters), fix that specific problem: check syntax
against the error, loosen an over-specific term, correct a field name or NCT number,
or switch a stats step to `studies`. Do not change parts of the plan that were not at fault.

## Unanswerable

Registry records hold design, status, dates, sponsors, sites, conditions,
interventions and enrollment. They do not answer efficacy, safety comparisons,
prices or medical advice. Also return unanswerable when the question refers to
something it never names ("this drug" with no drug given).

## Examples

"How has the number of pembrolizumab trials changed per year since 2015?"
```json
{"steps": [{"endpoint": "studies", "label": "Pembrolizumab", "params": {"query.intr": "\"pembrolizumab\"", "filter.advanced": "AREA[StartDate]RANGE[2015-01-01,MAX]"}}],
 "rationale": "Trials testing pembrolizumab that started in 2015 or later."}
```

"Compare phases for nivolumab vs pembrolizumab in melanoma"
```json
{"steps": [
  {"endpoint": "studies", "label": "Nivolumab", "params": {"query.intr": "\"nivolumab\"", "query.cond": "\"melanoma\""}},
  {"endpoint": "studies", "label": "Pembrolizumab", "params": {"query.intr": "\"pembrolizumab\"", "query.cond": "\"melanoma\""}}],
 "rationale": "Melanoma trials of each drug; phases are compared in the chart."}
```

"Which European countries have the most recruiting industry-sponsored asthma trials?"
```json
{"steps": [{"endpoint": "studies", "label": "Asthma", "params": {
  "query.cond": "\"asthma\"",
  "query.locn": "\"Germany\" OR \"France\" OR \"Italy\" OR \"Spain\" OR \"United Kingdom\" OR \"Netherlands\" OR \"Poland\" OR \"Belgium\"",
  "filter.overallStatus": "RECRUITING",
  "filter.advanced": "AREA[LeadSponsorClass]INDUSTRY"}}],
 "rationale": "Recruiting industry-sponsored asthma trials with sites in major European countries (Europe expanded to 8 countries)."}
```

"How are all registered trials split by phase and by overall status?"
```json
{"steps": [{"endpoint": "stats/field/values", "label": "All registered trials", "fields": ["Phase", "OverallStatus"]}],
 "rationale": "Registry-wide counts of the Phase and OverallStatus fields."}
```

"Where are the sites of NCT05064059?"
```json
{"steps": [{"endpoint": "study", "label": "NCT05064059", "nct_id": "NCT05064059"}],
 "rationale": "The one named trial; its site countries are in the record."}
```

## References: read only when needed

| Read | When |
| --- | --- |
| references/data-structure/index.md | You need a field not shown above, or a field's exact meaning (dates, design, eligibility, results, counters such as `NumInterventions`). The index lists every module of a study record; then read only that module's file |
| references/enums.md | You need the exact allowed values of an enum field |
| references/search-areas.md | Unsure which `query.*` parameter covers a concept, or which fields it searches |
| references/parameters.md | You need a parameter not in the tables above (e.g. `filter.geo`, `query.outc`, `types` on stats) |
| references/essie-syntax.md | Rare operators (`COVERAGE`, `EXPANSION`, `MISSING`, `DISTANCE`) or after a syntax error you cannot resolve |
