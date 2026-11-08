---
name: ctgov-search
description: >-
  Use this skill to plan which ClinicalTrials.gov data answers a question about clinical trials:
  state what the question means as typed search slots (drugs, conditions, lead sponsors,
  countries or a region, phases, statuses, study type, years, enrollment), one step per compared
  side, plus the breakdown the question asks for; or plan a single-trial lookup or registry-wide
  statistics. Code turns the slots into API calls. Use it for any question about trial counts,
  trends, comparisons, sponsors, places or phases.
metadata:
  api-version: "2.0.5"
  sources: docs/ctgov (official API snapshots)
---

# Planning ClinicalTrials.gov searches

You say **what the question means**; code decides how to query. For a `studies` step you fill
typed slots, and code:
- looks up how the registry names each drug, condition and sponsor, and also searches the
  registry's standard name (a brand also finds its generic: Ozempic -> semaglutide);
- adds the user's structured fields (they win over the question text);
- expands a region into its countries, compiles the API parameters, fetches every page,
  and counts. You never compute numbers.

**Code handles pagination, page sizes, fields and retries.** Write each search for the whole
question, however many trials it matches.

## Procedure

1. Read the question and the user's structured fields. Choose the endpoint (next section);
   almost every question is a `studies` search.
2. If the question compares named things (drug A vs B, condition X vs Y), write **one step
   per side**, identical except for the compared slot, each with a short label in the
   user's words. Comparing **attributes** of one set (phase 2 vs 3, industry vs academic, by
   year) is **one** step: the chart splits it later.
3. Fill the slots (table below). Write names as the user did; code adds standard names.
4. Set `breakdown`: what the question asks to break the answer down by (next sections).
5. Write a one-sentence rationale: what you fetched and any assumption you made.
6. If registry records cannot answer the question, answer `Unanswerable` with the reason.

## Which endpoint

| Question is about | `endpoint` | You provide |
| --- | --- | --- |
| Any set of trials defined by a drug, condition, sponsor, place, phase, status or date | `studies` | slots |
| One named trial ("NCT05064059") | `study` | `nct_id` |
| A fixed-value or text field across **all registered trials** ("how are all trials split by phase?") | `stats/field/values` | `fields`, e.g. `["Phase"]` |
| How many items a list field holds across all trials | `stats/field/sizes` | `fields`, e.g. `["Condition"]` |
| Study record sizes across the registry | `stats/size` | nothing |

**Whole-registry questions** (no condition, drug, sponsor, place, phase or date, e.g. "which drug
has the most trials?"): use `stats/field/values` with the field (`InterventionName`,
`LeadSponsorName`, `Condition`, `LocationCountry`, `Phase`, `OverallStatus`, `LeadSponsorClass`,
`InterventionType`). A `studies` search over the whole registry would fetch hundreds of
thousands of trials. Stats steps **cannot filter** (with user fields they are rejected) and give
only the top 250 values of text fields, with exact counts: that is the full answer to "which ...
has the most" and "top N" questions. Dates and numbers need `studies`.

## Slots of a `studies` step

| Slot | Meaning | Example |
| --- | --- | --- |
| `drugs` | Drugs or other interventions (any of them) | `["atezolizumab"]` |
| `drugs_match` | `"all"` = tested together in one trial (combination therapy) | `"all"` |
| `exclude_drugs` | Leave out trials naming these (needs `drugs`) | `["placebo"]` |
| `conditions` | Diseases or conditions (any of them) | `["atopic dermatitis"]` |
| `exclude_conditions` | Leave out (needs `conditions`): "hepatitis but not hepatitis B" | `["hepatitis B"]` |
| `sponsors` | **Lead** sponsors | `["Novartis"]` |
| `countries` | Countries with a site | `["Japan", "China"]` |
| `region` | `europe`, `asia`, `africa`, `north_america`, `south_america`, `oceania`; code expands it | `"asia"` |
| `phases` | `EARLY_PHASE1`, `PHASE1` ... `PHASE4`, `NA` | `["PHASE3"]` |
| `statuses` | Overall status enums | `["RECRUITING"]` |
| `study_type` | `any` (default), `interventional`, `observational` | `"interventional"` |
| `min_enrollment`, `max_enrollment` | Enrollment range, inclusive | `501` |
| `period` | Years on start or completion date | `{"field": "start", "from_year": 2015}` |
| `keywords` | Other words to find anywhere (acronyms, techniques) | `["CAR-T"]` |
| `advanced` | Escape hatch: one Essie expression for a filter no slot covers (shown to the reader) | `AREA[DesignAllocation]RANDOMIZED` |

## Rules

- **Brand and code names:** write them as given. Code looks up how the registry indexes them
  and also searches the standard name; do not add synonyms yourself.
- **Drug classes have no registry name:** expand a class into its member drugs and say so in the
  rationale (`"JAK inhibitor"` finds 303 trials; tofacitinib, baricitinib and upadacitinib find 645).
- **Sponsor aliases are not resolved by the registry:** write the registered lead-sponsor name
  when you know it ("MSD" is registered as "Merck Sharp & Dohme LLC"), and say so.
- **Regions:** use `region`; code expands it into the registry's country names and charts only
  those countries. A region written as a country matches facility names, not the continent.
- **Study type stays `any`** unless the question explicitly asks for interventional (treatment)
  or observational studies. Code states the scope to the reader.
- **"Ongoing"** = statuses `NOT_YET_RECRUITING`, `RECRUITING`, `ENROLLING_BY_INVITATION`,
  `ACTIVE_NOT_RECRUITING`.
- **"Completed" trials** = statuses `["COMPLETED"]`; a completion **date** alone also counts trials
  still running or stopped. "Completed each year" = `statuses: ["COMPLETED"]` plus a `completion` period.
- **Years go in `period`** (inclusive, either end open): `start` unless the question is about
  trials completed or finishing. "Since 2015" = `from_year: 2015`; "in 2018" = from and to 2018.
  The chart's time axis must use the matching year. Never write dates in `advanced`.
- **`advanced` is only for what no slot covers**: design (`AREA[DesignAllocation]RANDOMIZED`,
  `AREA[DesignMasking]QUADRUPLE`, `AREA[DesignPrimaryPurpose]TREATMENT`), `AREA[LeadSponsorClass]INDUSTRY`,
  `AREA[InterventionType]DEVICE`, counters (`AREA[NumInterventions]RANGE[2,MAX]`), results
  (`AREA[HasResults]true`), same-site conditions (`SEARCH[Location](AREA[LocationStatus]RECRUITING)`).
  Phases, statuses, study type, enrollment, sponsors, drugs, conditions and countries have slots;
  writing them in `advanced` is rejected. Enum values are UPPER_SNAKE_CASE (references/enums.md).
- Do not narrow a question beyond what it asks to get fewer results: large sets are code's problem.

## Breakdown

Set `breakdown` to what the question asks to break the answer down by: one of `phase`,
`start_year`, `completion_year`, `overall_status`, `lead_sponsor`, `sponsor_class`, `condition`,
`intervention`, `intervention_type`, `country`, `enrollment`, `duration_months`, `study_type`, `allocation`,
`masking`, `primary_purpose`, `group` (the compared sides). Two numbers plotted against each other
("enrollment against duration") are written like a network: `"enrollment x duration_months"`.
A relationship question (a network) names **both node kinds** joined by ` x `:
`"lead_sponsor x intervention"` (which sponsors test which drugs), `"condition x intervention"`,
`"intervention x intervention"` (drugs used together). These are supported. If it asks for a breakdown the data cannot chart (US state, city, site, investigator), write `"unsupported: <what>"`: you will then answer Unanswerable,
never chart the nearest field instead. Leave it out when the question asks for no breakdown.
The chart you choose later must show this breakdown.

## Multi-step questions

When the question depends on a value you must find first ("the sponsor with the most glioblastoma
trials", "the drugs most often tested alongside a named drug"):
1. fetch the set that reveals it, call describe_data, and read the value from the profile's
   top values (code-computed counts; never guess it);
2. fetch again with that value (a sponsor goes in `sponsors`: lead sponsor), and say in the
   rationale what you found ("<sponsor> leads glioblastoma with <N> trials", the profile's count);
3. the chart is built from the latest successful fetch, so that fetch must hold everything shown.

**Several found values** (more than 4 sponsors, drugs or countries read from a profile): put them
all in **one** step's slot (e.g. `sponsors: [six names]`) and chart by that field, e.g.
`lead_sponsor` as the series; separate steps are for up to 4 named sides.

**Ties:** if the profile lists `tied_for_top` for the value you need, never pick one of them.
Fetch every tied value as its own step (up to 4) and say there is a tie. **Few trials:** if a fetch
matches a handful of trials, say the ranking rests on very few trials.

## User's structured fields

They are listed in the request; code puts them in the same slots. **The field wins** when the
question text disagrees (`condition: melanoma` with "show lung cancer trials" means melanoma
trials); code replaces your term and tells the reader, so plan for the field's value. A narrower
term that contains the field's value ("uveal melanoma") is kept. In a comparison, a field that is
one of the compared sides is fine; a comparison of other values is sent back. `sponsor` is the
**lead** sponsor. `start_year` / `end_year` are an inclusive start-date range and replace your
start period.

## Feedback

If you receive feedback ("not found", "no trials matched", a conflict with the user's fields, an
API error about `advanced`), fix that specific problem and keep the rest of the plan.

## Unanswerable

Registry records hold design, status, dates, sponsors, sites, conditions, interventions and
enrollment. They do not answer efficacy, safety comparisons, prices or medical advice. Also
answer Unanswerable when the question refers to something it never names ("this drug" with no
drug given), or asks for a breakdown marked unsupported.

## Examples

"Atezolizumab trials started per year from 2018 on"
```json
{"steps": [{"endpoint": "studies", "label": "Atezolizumab", "drugs": ["atezolizumab"], "period": {"field": "start", "from_year": 2018}}],
 "breakdown": "start_year",
 "rationale": "Trials testing atezolizumab that started in 2018 or later."}
```

"Durvalumab or atezolizumab in bladder cancer: phase mix of each"
```json
{"steps": [
  {"endpoint": "studies", "label": "Durvalumab", "drugs": ["durvalumab"], "conditions": ["bladder cancer"]},
  {"endpoint": "studies", "label": "Atezolizumab", "drugs": ["atezolizumab"], "conditions": ["bladder cancer"]}],
 "breakdown": "phase",
 "rationale": "Bladder cancer trials of each drug; phases are compared in the chart."}
```

"East Asian sites of recruiting, industry-run atopic dermatitis trials"
```json
{"steps": [{"endpoint": "studies", "label": "Atopic dermatitis", "conditions": ["atopic dermatitis"],
  "countries": ["Japan", "China", "South Korea", "Taiwan"], "statuses": ["RECRUITING"],
  "advanced": "AREA[LeadSponsorClass]INDUSTRY"}],
 "breakdown": "country",
 "rationale": "Recruiting industry-sponsored atopic dermatitis trials with sites in four East Asian countries."}
```

"Glioblastoma studies finished each year from 2012"
```json
{"steps": [{"endpoint": "studies", "label": "Glioblastoma", "conditions": ["glioblastoma"], "statuses": ["COMPLETED"],
  "period": {"field": "completion", "from_year": 2012}}],
 "breakdown": "completion_year",
 "rationale": "Completed glioblastoma trials by completion year, from 2012."}
```

"How are all registered trials split by phase and by overall status?"
```json
{"steps": [{"endpoint": "stats/field/values", "label": "All registered trials", "fields": ["Phase", "OverallStatus"]}],
 "breakdown": "phase",
 "rationale": "Registry-wide counts of the Phase and OverallStatus fields."}
```

"Where are the sites of NCT05064059?"
```json
{"steps": [{"endpoint": "study", "label": "NCT05064059", "nct_id": "NCT05064059"}],
 "breakdown": "country",
 "rationale": "The one named trial; its site countries are in the record."}
```

## References: read only when needed

| Read | When |
| --- | --- |
| references/data-structure/index.md | You need a field for `advanced` not shown above, or a field's exact meaning (dates, design, eligibility, results, counters). The index lists every module of a study record; then read only that module's file |
| references/enums.md | You need the exact allowed values of an enum field |
| references/search-areas.md | Unsure which fields a slot searches (drugs = InterventionSearch, conditions = ConditionSearch, ...) |
| references/parameters.md | You need to know what the compiled parameters do (`filter.geo` and others are not slots yet) |
| references/essie-syntax.md | Rare operators in `advanced` (`COVERAGE`, `EXPANSION`, `MISSING`, `DISTANCE`) or after a syntax error |
