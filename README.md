# Cheiron: ClinicalTrials.gov query-to-visualization backend

Turns a natural-language question about clinical trials (plus optional structured fields) into
one visualization spec (type, title, encoding, data with citations) and metadata, backed by the
ClinicalTrials.gov API v2.

## Running it

```bash
cp .env.example .env          # set OPENAI_API_KEY; CHEIRON_PLANNER_MODEL=openai:gpt-5.4
uv sync
PYTHONPATH=src uv run uvicorn cheiron.api.app:app --port 8765
```

`PYTHONPATH=src` works around iCloud Drive hiding the virtualenv's `.pth` file. It isn't needed
outside iCloud.

Ask a question (runs as a background task) and poll for the result:

```bash
curl -s -X POST localhost:8765/queries -H 'content-type: application/json' \
     -d '{"query": "How are breast cancer trials distributed across phases?"}'
curl -s localhost:8765/queries/<task_id>
```

Interactive API docs: http://localhost:8765/docs

## Request and response schema

The machine-readable schema is committed at [`docs/api/openapi.json`](docs/api/openapi.json)
(regenerate with `uv run python scripts/export_openapi.py`; a test fails if it drifts). With the
service running it is also served at `/openapi.json`, with interactive docs at `/docs` and
`/redoc`. Real requests and responses for each question class are in [`examples/`](examples/).
This section explains what the schema alone does not.

### Endpoints

| Method | Path | Body / result |
|---|---|---|
| `POST` | `/queries` | `QueryRequest` → `202` with a task (`Location: /queries/{task_id}`). `422` if the request is invalid |
| `GET` | `/queries/{task_id}` | The task: `status` (`queued`, `running`, `succeeded`, `failed`), `progress` (stage and message), `result` (a `QueryResponse` when succeeded), `error` (an `ErrorResponse` when failed). `404` once forgotten (tasks are kept 24 h, in memory) |
| `GET` | `/health` | `{"status": "ok"}` |

A query takes seconds to a minute (it fetches every matching trial), so it runs as a task: poll
`GET /queries/{task_id}` until `status` is `succeeded` or `failed`.

### Request: `QueryRequest`

| Field | Type | Required | Validation |
|---|---|---|---|
| `query` | string | yes | 3–500 characters: the question |
| `drug_name` | string | no | 1–200 characters |
| `condition` | string | no | 1–200 characters |
| `sponsor` | string | no | 1–200 characters; the **lead** sponsor |
| `country` | string | no | 2–100 characters; a country with a trial site |
| `trial_phase` | list of `EARLY_PHASE1`, `PHASE1`, `PHASE2`, `PHASE3`, `PHASE4`, `NA` | no | at least one |
| `recruitment_status` | list of `NOT_YET_RECRUITING`, `RECRUITING`, `ENROLLING_BY_INVITATION`, `ACTIVE_NOT_RECRUITING`, `COMPLETED`, `SUSPENDED`, `TERMINATED`, `WITHDRAWN`, `UNKNOWN` | no | at least one |
| `start_year`, `end_year` | integer | no | 1900–2100, `start_year` ≤ `end_year`; an inclusive range on the trial **start** date |

Unknown fields are rejected (`422`), so a typo cannot be silently ignored. Structured fields
always apply: when the question text and a field disagree ("lung cancer trials" with
`condition: melanoma`), the field wins and `meta.assumptions` says what was replaced.

```json
{"query": "How has the number of trials for this drug changed over time?", "drug_name": "Pembrolizumab"}
```

### Response: `QueryResponse`

```
QueryResponse
├── visualization   one chart or network (shape picked by `type`)
│   ├── type        bar_chart | grouped_bar_chart | stacked_bar_chart | time_series | histogram | scatter_plot | network_graph
│   ├── intent      what it shows: change_over_time, ranking, distribution, magnitude, part_to_whole, correlation, spatial, relationship
│   ├── title
│   ├── encoding    which data field goes on which visual channel (Vega-Lite vocabulary)
│   └── data        rows (charts) or {nodes, edges} (network); each carries its sources
├── meta            how it was computed: interpretation, filters, assumptions, warnings, units, counts, data date
└── vega_lite       the same chart as a ready-to-render Vega-Lite v5 spec (null for networks)
```

#### `encoding` (charts)

`x`, `y` and optional `color` (series), `xOffset` (grouped bars side by side) and `x2` are
**channels**:

| Channel key | Meaning |
|---|---|
| `field` | The key in each data row |
| `type` | `quantitative` (numbers), `nominal` (categories), `ordinal` (ordered categories), `temporal` (ISO dates) |
| `title` | Axis or legend title |
| `sort` | `"-y"` = largest first; a list = explicit order (phases in clinical order) |
| `timeUnit` | `utcyear` on time axes: each row's date is the 1st of January of its year |
| `scale` | `"log"` where values are heavily skewed (enrollment in scatter plots) |
| `labels` | Display name per coded value: `{"PHASE1": "Phase 1", "ACTIVE_NOT_RECRUITING": "Active, not recruiting"}`. Rows keep the registry's codes; show the label when there is one, else the value |

Fields a chart can use: `phase`, `start_year`, `completion_year`, `overall_status`, `lead_sponsor`,
`sponsor_class`, `condition`, `intervention`, `intervention_type`, `country`, `study_type`,
`allocation`, `masking`, `primary_purpose`, `enrollment`, `duration_months`, and `group` (the side
of a comparison, e.g. one drug).

#### `data` rows, by chart type

Every row has the encoded fields plus `citations` and `nct_ids` (below).

| `type` | One row per | Value fields |
|---|---|---|
| `bar_chart` | Category | `<x field>`, `trial_count` |
| `grouped_bar_chart`, `stacked_bar_chart` | Category × series value | `<x field>`, `<series field>`, `trial_count` |
| `time_series` | Year (empty years included as 0) | `start_year` or `completion_year` as `"2015-01-01"`, `trial_count` (plus a series field if any) |
| `histogram` | Enrollment bin | `enrollment_range` (label, e.g. `"50–99"`, `"10,000+"`), `enrollment_from`, `enrollment_to` (**exclusive**; `null` = no upper bound), `trial_count` |
| `scatter_plot` | Trial | `enrollment`, `duration_months` (start to actual primary completion), optional series field |
| any bar or time series with a share | as above | adds `percent` (0–100) and `of_trials` (its denominator); `y` charts `percent` |

Counts are **distinct trials**. A field a trial can have several values of (phase, condition,
intervention, intervention type, country) counts the trial once per value, so bars can add up to
more than `meta.trials_analyzed`; `meta.assumptions` says so when it applies.

#### `network_graph`

`data` is a NetworkX node-link graph (`networkx.node_link_graph(data, edges="edges")` reads it):

- `nodes`: `id`, `label`, `group` (the node kind, e.g. `lead_sponsor`, `intervention`), `size` (trials with this value)
- `edges`: `source`, `target` (node ids), `weight` (trials that have both values)
- `encoding` names those keys (`node_label`, `node_group`, `node_size`, `edge_weight`) and gives `group_labels` for display.

#### Sources: `citations` and `nct_ids`

Every bar, time bucket, bin, scatter point, node and edge carries:

| Key | Meaning |
|---|---|
| `nct_ids` | **Every** trial counted in this data point (complete, sorted) |
| `citations` | The first few of them in detail: `nct_id`, `excerpt` (the exact text or value from the API record that put the trial here, e.g. `"PHASE2"` or a start date as written, `"2018-03"`), `field` (the API field path it came from), `title` (the trial's brief title, exactly as in the API; given once per trial within a data point) |

Answers built from registry-wide statistics (`/stats`, e.g. "which drug has the most trials?")
have counts but no per-trial sources; `meta.warnings` says so.

#### `meta`

| Field | Meaning |
|---|---|
| `interpretation` | What was searched, in plain words, written by code from the executed searches |
| `request_filters` | The structured fields the user sent, as sent |
| `filters_applied` | `{"steps": [...]}`: the exact API calls (`params`), what the agent asked for (`intent`), and names also searched under the registry's standard name (`searched_as`, e.g. Ozempic → semaglutide) |
| `assumptions` | Counting rules and decisions the reader needs (multi-valued fields, replaced terms, what a percentage is of) |
| `warnings` | Missing values excluded, categories cut to the top N, partial current year, samples |
| `units` | What each number counts, by data key (`trial_count`: trials; `percent`; `size`, `weight`; `enrollment`: participants) |
| `total_trials_matched`, `trials_analyzed` | Matches at the source, and trials aggregated |
| `data_as_of`, `api_version`, `source` | ClinicalTrials.gov data refresh time, API version, `"clinicaltrials.gov"` |
| `chain` | Every fetch the agent made, in order, with its rationale (the agent's own words) and status |
| `metrics` | Run time, tokens and tool calls |

#### Errors: `ErrorResponse`

`{"error": <code>, "message": <text for the user>, "details": {...}}` with `error` one of
`invalid_request`, `unsupported_query` (registry data cannot answer it, e.g. efficacy, or a
breakdown by a field that is not available, such as US state), `no_results`, `upstream_error`
(ClinicalTrials.gov failed), `internal_error`.

## Design decisions

1. **The model never computes a number.** One agent (`agents/query_agent.py`) plans and chooses;
   code fetches, counts, cites and builds the chart. The agent sees a *profile* of the fetched data
   (distinct values, top values with counts, missing values), never the records, and answers with
   a chart plan. Every number in a response is counted by code from trial records.
2. **The agent states intent; code builds the query** ([design note](docs/design/search-intent.md)).
   The agent fills typed slots (drugs, conditions, lead sponsors, countries or a region, phases,
   statuses, study type, years, enrollment) instead of writing API syntax. Code then:
   - resolves names to the registry's own: a brand or code name is also searched under the MeSH
     term its trials are indexed under (Ozempic → semaglutide), only when that term dominates the
     sampled trials and the name is not itself an index term;
   - merges the user's structured fields into the same slots (the field wins, recorded in meta);
   - keeps comparison sides apart when resolution would merge them (Ozempic vs Wegovy);
   - expands regions using the registry's live country list, and charts only those countries;
   - applies one study-type rule (all studies unless the question asks otherwise).
3. **Skills, loaded on demand** (Agent Skills format, `agents/skills/`): `ctgov-search` for
   planning searches, `chart-planning` for choosing charts, each with references read only when a
   rule says so. Skill examples never reuse eval questions (a test guards this).
4. **Every choice is validated in code before it is used**, and sent back to the agent with the
   reason if it fails: plan schema, conflicts with the user's fields, chart rules (series where
   needed, no stacking of multi-valued fields, time axis matching the searched dates), the chart
   fitting the fetched data, and the chart showing the breakdown the plan said the question asks
   for. A breakdown the data cannot chart (by state, by investigator) must be refused, never
   swapped for the nearest field.
5. **Exact sources.** Citations quote the API record exactly (dates as written, `"2018-03"`), with
   the field path and title; `nct_ids` lists every trial behind every value.
6. **Frontend-friendly output.** Vega-Lite's vocabulary for encodings (so `encoding` is
   unambiguous) plus a ready Vega-Lite spec; display names for coded values; NetworkX node-link
   format for networks.
7. **Correct counts over speed.** Every page of every search is fetched (no sampling), all steps
   run on one registry data version (refetched if the registry refreshes mid-fetch), and queries
   run as background tasks with progress.
8. **Evals that check correctness, not just shape** (`evals/`): live cases tagged by question
   class, with checks on recall against hand-written reference searches, charted labels, the
   executed filters, exact citations (offline and live) and API recounts.

Trade-offs:

| Choice | Cost |
|---|---|
| Fetch every matching trial | Broad questions are slower (tens of thousands of trials) |
| Complete `nct_ids` on every value | Larger responses: median about +27 KB; the network and scatter examples are under 1 MB |
| Typed slots instead of free API syntax | Rare filters go through `advanced`, an escape hatch validated only by the API (and flagged in meta) |
| Standard name only when it dominates (≥50% of sampled trials) | Brands indexed under mixed terms may not expand; never expands to a co-tested drug |
| Study type defaults to all studies | Matches clinicaltrials.gov; "trials" questions include observational studies unless asked otherwise |
| Scatter samples 1,000 points | Large sets show an even (hashed) sample, stated in warnings |

## Limitations

- **Investigators and sites are not available.** Networks of investigators or trial sites, and
  breakdowns by US state, city or facility, are refused with the reason. Site fields exist in the
  API but triple the response size, and investigator names are noisy.
- **Sponsor aliases depend on the model.** The registry has no canonical sponsor names ("MSD"
  matches six small MSD entities, not Merck Sharp & Dohme LLC); the skill tells the agent to write
  the registered name.
- **Drug classes** ("GLP-1 agonists") have no registry field: the agent expands them into member
  drugs from its own knowledge.
- **Network nodes** merge spellings that differ by case or punctuation only; other variants
  ("Metformin" / "Metformin Hydrochloride") and non-drug interventions (procedures, tests) can
  still appear as separate nodes. Placebo and sham are excluded.
- **Scatter plots** cover enrollment against duration only; duration exists only for finished trials.
- **One process, in-memory tasks:** task status is lost on restart (saved outputs remain) and not
  shared between workers.
- **Evals** run each case once (a model choice can vary between runs), check recall only where a
  case defines a reference search, and `evals/results/report.json` is overwritten by every run.

With more time:

1. Site fields fetched only when a question needs them (US state, city, facility networks), and
   investigators with a cleanup list.
2. A sponsor alias table, built from the registry's lead-sponsor names.
3. Network nodes keyed by MeSH terms (merging salts and spellings), and drug-only networks.
4. Evals: each case 3 times with pass rates, a history of runs, a committed baseline, and a check
   of the agent's intent slots (`meta.filters_applied` already carries them).
5. A persistent task store (e.g. Redis or a database) for several workers.
6. An endpoint for a data point's full sources, so very large responses can omit `nct_ids`.

## Use of AI tools

- **Building it:** developed with Claude Code (Anthropic) as a pair programmer: code, tests,
  skills, eval cases and documentation were written with it, in small reviewed steps. Design
  decisions (the typed search intent, name resolution, the user's fields winning, complete
  sources on every value, the eval checks) were discussed and chosen before they were built.
- **Reviewing it:** two adversarial agents (one questioning, one defending the evals) reviewed
  the eval suite against the brief; their findings became the recall, label and filter checks
  and the `grilled` eval suite.
- **Running it:** the query agent uses an OpenAI model (`CHEIRON_PLANNER_MODEL`).
- **How correctness was validated:**
  - 261 unit tests with fake models and fake registries (no API key needed);
  - live evals: 72 cases against the real model and API; all pass in the latest report, where the
    cases each change affected were rerun live after it (a single full rerun is still to do);
  - every number quoted in a skill or this README was checked against the live API;
  - the web UI was checked with screenshots of real responses.

## Evals

An eval is a test case with an expected outcome, run against the **live service** and checked
automatically. Unit tests (`tests/`) check the code with fakes. Evals check the whole system:
the real model, the real ClinicalTrials.gov API, and the response a user would get. Details of
every check are in [`evals/README.md`](evals/README.md).

```
evals/
  cases/<suite>.json   the test cases (brief, structured, users, refusals, multistep)
  checks.py            the fixed tag list and every check
  run.py               runs cases, checks answers, prints coverage by tag
  results/             run outputs (gitignored)
```

### Running

With the service on port 8765:

```bash
uv run python evals/run.py                         # every case
uv run python evals/run.py --suite=brief,refusals  # some suites
uv run python evals/run.py --only=b3,m1            # some cases
uv run python evals/run.py --regrade               # re-check saved responses, no service calls
uv run python evals/run.py --coverage              # what the cases cover, no runs
```

Every run ends with a coverage table per tag: the number of cases, how many ran, how many
passed, and which ones failed. `NO CASES` marks categories nothing tests yet.

### Adding an eval

1. Add one line to the right file in `evals/cases/`:

   ```json
   {"id": "u12", "intent": "Sponsor alias: MSD vs Merck Sharp & Dohme",
    "tags": ["input.sponsor_alias", "chart.time_series"],
    "request": {"query": "How many phase 3 trials does MSD run per year?"},
    "expect": {"outcome": "answered", "chart": ["time_series"]}}
   ```

   - `intent` (one line on what the case tests) and `tags` are required.
   - `request` is sent as-is to `POST /queries`.
   - `expect.outcome` is `answered`, `refused` or `either`.
   - Optional expectations (all listed in [`evals/README.md`](evals/README.md); unknown keys stop the run):
     - `chart`, `x`: the allowed chart types and the x-axis field
     - `recall`: reference searches whose trials the answer must mostly contain
     - `labels_within` / `labels_exclude`: allowed or forbidden charted categories
     - `filters_include` / `filters_exclude`: text that must or must not be in the executed searches
     - `units_include`, `refusal_mentions`, `meta_mentions`, `data_excludes`

   Only expect what the question really decides.
2. If the case needs a new category, add the tag with a one-line description to `TAGS` in
   `evals/checks.py`. Unknown tags stop the run. If it needs a new kind of verification, add a
   `check_…` function there and list it in `CHECKS`.
3. Run `evals/run.py --coverage` to see where it lands, then `evals/run.py --only=u12`.

### Where outputs are stored

Eval definitions and eval outputs are kept apart:

| What | Where | In git |
|---|---|---|
| Eval definitions: cases, checks, runner | `evals/cases/`, `evals/checks.py`, `evals/run.py` | yes |
| Run results: each response and the pass/fail report | `evals/results/` | no |
| Full query output: fetched trials, profile, agent trace, metrics | `data/queries/<task_id>/`, written by the service | no |

A saved response links to its full output through `output_dir`, so nothing is copied twice.

Right now `evals/results/responses/<id>.json` and `report.json` are overwritten on every run.
Planned:
- keep each run in its own folder (`evals/results/<run time>/`) with the model, git commit and
  data date, so runs can be compared before and after a change
- commit one small baseline report as evidence
