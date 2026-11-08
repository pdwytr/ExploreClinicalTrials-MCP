# Design: plan by intent, compile in code

Status: implemented. Replaces the free-text `/studies` step.

## Problem

The agent used to write ClinicalTrials.gov parameters itself (`query.intr: "\"Ozempic\""`,
`filter.advanced: "AREA[Phase]PHASE3 AND ..."`). Code could check that a search was well formed,
never what it meant, because the drug, condition, sponsor, scope and comparison only existed
inside strings. An adversarial review of the evals found 12 problems; 7 sat at this boundary:

| Finding | Why the old design let it through |
|---|---|
| Brand names (Ozempic: 104 trials vs semaglutide 799) | Recall depended on the model knowing the generic name |
| Sponsor aliases (MSD: 7 trials vs 2,198 for Merck Sharp & Dohme) | Same: no registry lookup |
| Conflicting structured field (r22: "lung cancer" AND "melanoma") | Code had to parse strings to see a conflict |
| `sponsor` field matched collaborators | One string parameter chosen for the field |
| Study type applied in 15 answers, not in 36 | A prose rule in the skill, re-decided per question |
| Silent swap ("by state" answered by country) | The asked-for breakdown was never stated anywhere |
| Region asked, other countries charted | The region existed only inside a search string |

Fixes made at the string level (substring "contains" checks, rewriting terms inside the agent's
strings) worked but kept piling up. The fix is structural: the agent states **what** it means,
code decides **how** to query.

## Design

```
question + structured fields
   │
   ▼  agent
SearchPlan: steps of typed slots + the breakdown the question asks for
   │
   ▼  code: resolve      each drug / condition / sponsor name -> its registry form
   ▼  code: merge        the user's structured fields fill the same slots; the field wins
   ▼  code: compile      slots -> API parameters, with every scope rule in one place
   ▼  fetch -> profile -> ChartPlan -> builder (unchanged)
   ▼  code: meta         interpretation rendered from what ran, not from the model's prose
```

### 1. The agent's search step is typed (`StudiesStep`)

| Slot | Meaning | Compiled to |
|---|---|---|
| `drugs`, `drugs_match` (`any` / `all`) | Interventions; `all` = combination therapy | `query.intr` |
| `conditions`, `exclude_conditions` | Conditions, and ones to leave out | `query.cond` |
| `sponsors` | **Lead** sponsors | `query.lead` |
| `countries`, `region` | Site countries; a region is expanded by code | `query.locn` |
| `statuses`, `phases` | Enums | `filter.overallStatus`, `AREA[Phase]` |
| `study_type` | `any` (default), `interventional`, `observational` | `AREA[StudyType]` |
| `min_enrollment`, `max_enrollment` | Enrollment range | `AREA[EnrollmentCount]RANGE` |
| `period` | Year range on start or completion date (unchanged) | `AREA[StartDate\|CompletionDate]RANGE` |
| `keywords` | Free terms (acronyms, "CAR-T") | `query.term` |
| `advanced` | Escape hatch: a raw Essie expression for anything else (design fields, counters) | AND-ed onto `filter.advanced`, flagged in meta |

The agent can no longer write `query.intr`, `query.cond`, `query.lead`, `query.spons`,
`query.locn` or `filter.overallStatus` directly. Registry-wide `stats/*` steps and single-trial
lookups are unchanged.

The plan also states `breakdown`: the dimension the question asks to break the result down by
(a chartable field, or `unsupported` with the words used, e.g. "US state").

### 2. Resolver (code, deterministic)

For each name, one registry call samples up to 50 matching trials:

- **Drug / condition:** the MeSH term on the most sampled trials. If it is on at least half of
  them and differs from the name, both are searched (`"Ozempic" OR "semaglutide"`). Only the
  dominant term: comparator drugs and co-conditions on a minority of trials are ignored, and
  parent categories are never added. Searched as text, not as a MeSH filter (not every trial
  is MeSH-indexed: 596 indexed vs 799 by text for semaglutide).
- **Sponsor:** the lead-sponsor name on most trials that mention the name (MSD → Merck Sharp &
  Dohme LLC); both are searched as lead sponsor.
- **Region:** a fixed table of countries (`$EUROPE`, ...), also used to keep the chart's country
  axis inside the region.

Every resolution is recorded with its evidence ("Ozempic: 43 of 50 sampled trials are indexed
as semaglutide") and shown in `meta.assumptions`. Lookups are cached per process.

### 3. Comparisons

Sides are steps that differ in one slot. Each side is resolved on its own; then, if a side's
added standard name is another side's name or standard name (Ozempic vs Wegovy, both
semaglutide; Ozempic vs semaglutide), the expansion is dropped for those sides and a warning
says why. Side labels are always the user's words.

### 4. Structured fields win (code)

`drug_name`, `condition`, `sponsor`, `country`, `trial_phase`, `recruitment_status` and the years
fill the same slots. If the agent's slot names something else, the field replaces it and meta
says so ("The question said lung cancer; condition=melanoma was used"). In a comparison, a field
that is one of the compared sides is skipped (as before); one that is none of them sends the
plan back, because replacing every side would erase the comparison.

### 5. Breakdown consistency (code)

A chart is accepted only if it charts the breakdown the plan stated. `unsupported` means the
question cannot be answered as asked: the agent must answer `Unanswerable` with the reason,
instead of charting the nearest field it has (r05: states answered with countries).

### 6. Meta from code

`meta.interpretation` is rendered from the compiled steps (what was actually searched, scope,
period). The agent's rationale stays in `meta.chain`, labelled as the agent's.

### 7. Charts

- `country` charts of a region- or country-restricted search show only those countries.
- Placebo and sham arms are not counted as interventions (they topped "most common drug"
  rankings and appeared as drug nodes in networks).

## Not changed

Counting, citations, chart validation and the builder: the model still never writes a number.

## Trade-offs

- **Coverage moves to `advanced` for rare filters.** It is validated by the API only and flagged
  in meta, so its use stays visible.
- **One extra registry call per name** (about a second), cached. No extra model calls.
- **Dominance threshold (50%).** Too low expands to comparators; too high misses brands with
  mixed indexing. Measured on brands, code names and conditions.
- **A question about a brand only ("trials that name Ozempic") is widened to the molecule.**
  Rare; meta states the expansion.

## Results

Live, all 72 eval cases (brief, structured, users, refusals, multistep, grilled): **70 pass**,
against 55 before this change under the same checks. Fixed by it: brand names (r07, g02), a
sponsor alias (g01, via the skill's registered-name rule), conflicting fields (r22, g09),
unsupported breakdowns refused (r05, g05), regions (u2, g07), "completed" (u7, g03), recall of
condition spellings (u6), placebo nodes (b9, r10, r11, g10). Still failing: share questions
(x2, g08), which need percent output.

Not done yet: an `expect.intent` eval check on the compiled slots (`meta.filters_applied` now
carries `intent` and `searched_as`, so it is a small addition); sponsor aliases resolved in code
(the registry has no canonical sponsor names: "MSD" matches six small MSD entities, not Merck
Sharp & Dohme LLC, so this needs an alias table rather than a registry lookup).
