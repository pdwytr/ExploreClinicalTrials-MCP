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

The system has two kinds of parts: an **agent** for what needs judgement, and **deterministic
layers** (plain code) for everything that can be checked. Most decisions below are about where
that line sits, and they changed as the evals showed what failed.

### 1. What the agent does, and what it never does

The agent interprets: it turns a question into a search plan, decides whether a second fetch is
needed (multi-step questions), chooses the chart, or refuses. It never touches data: code fetches,
counts, cites, labels and writes the metadata. The model never writes a number, so it cannot
invent one.

- *Trade-off:* the agent can only express what the plan and chart models allow; anything new
  (shares, scatter, design fields) needs code, not a prompt change. In exchange every number is
  reproducible and every value traceable to trial records.

### 2. One agent with tools, not a pipeline of two agents

The first design was a pipeline: a search-planner agent, then code, then a chart-planner agent.
It was replaced by **one agent with four tools**: `fetch_data` (code runs the plan),
`describe_data` (a profile of what was fetched), `load_skill`, `read_reference`.

- *Why:* questions like "the sponsor with the most melanoma trials, and its trials per year" need
  fetch, look, fetch again; and the right chart depends on what the data turned out to be. A fixed
  pipeline cannot loop; one agent can, within a budget of 5 fetches, each recorded in `meta.chain`.
- *Trade-off:* one agent carries both jobs in its context, so the chart knowledge is a separate
  skill loaded only when needed (next sections), and code enforces the order (no chart before data).

### 3. Search accuracy: skills and typed intent, not free text, templates or retrieval

Options considered: hard-coded query templates per question type (accurate but brittle, fails on
anything new), the model writing raw API queries (wide coverage, but correctness depends on the
model), fine-tuning or RAG over the docs (opaque, needs data the project does not have).

The search plan went through three versions:

| Version | Why it changed |
|---|---|
| Typed plan (fixed fields) | Too narrow: could not express what the API supports |
| The agent writes API syntax, code checks it | Wide coverage, but evals found wrong answers that passed: brand names searched instead of generics (13% of the trials), conflicting fields intersected, regions charting other continents. Fixes became string parsing piled on string parsing |
| **Typed intent compiled by code** (current) | The agent states *what* (drugs, conditions, lead sponsors, countries or a region, phases, statuses, study type, years, enrollment); code decides *how*. An `advanced` escape hatch keeps the coverage of version 2 for rare filters, flagged in meta |

Names are resolved against the **registry's own vocabulary**, not the model's memory: code samples
the trials a name matches and also searches the MeSH term they are indexed under (Ozempic is
indexed as semaglutide: 104 trials by name, 799 by generic). Only the dominant term is added, never
a co-tested drug, and never when the name is itself an index term. A MeSH linker was first
prototyped as an eval probe and dropped; resolution from samples of matching trials replaced it.
Details: [docs/design/search-intent.md](docs/design/search-intent.md).

### 4. Context: metadata, not records

The agent never sees trial records, which can number tens of thousands. `fetch_data` returns only
totals per step and what was searched; `describe_data` returns a **profile**: per field the
distinct values, missing count, top 10 values with trial counts, whether a trial can have several
values, ties at the top, numeric summaries. That is enough to choose a chart and small enough to
fit any query. The records stay on disk (`data/queries/<id>/fetch-N/`) for the code that counts
and cites them.

### 5. Knowledge: skills read on demand, not vector retrieval

The knowledge the agent needs is small, structured and authoritative: the ClinicalTrials.gov API
reference (24 record modules, 41 enums, every search area and parameter). Instead of embedding it
for similarity search, it is organised as **skills** (Agent Skills format) with **progressive
disclosure**:

- `ctgov-search/SKILL.md` (in the prompt): the procedure, the slots, rules learned from the live
  API, multi-step patterns, examples. Its references (generated from official API snapshots in
  `docs/ctgov/` by `scripts/build_ctgov_skill.py`) are read only when a table row says when.
- `chart-planning/SKILL.md` (loaded once data is fetched): a default chart per question class,
  gotchas, and references for networks, registry statistics and chart rules.

*Why not RAG:* the agent should navigate an index deterministically ("read `enums.md` when you need
an enum's values"), not hope a similarity search returns the right chunk; every reference read is
recorded in the trace. A version check warns when the live API moves past the documented snapshot.
*Trade-off:* the skills need curation, and this does not scale to a large, unstructured corpus.

### 6. Making skills reliable

- Follow the Agent Skills spec (frontmatter, size limits, references one level deep, "read when"
  pointers) — enforced by tests.
- Defaults, not menus: one default chart per question class; gotchas for the known traps.
- Every example in a skill is validated by a test as a real plan or chart; a skill may only teach
  API parameters the code accepts.
- Every fact in a skill was checked against the live API, with the numbers quoted.
- **No eval question may appear in a skill** (a test compares them), so evals measure judgement,
  not copying.

### 7. Validating what goes into and comes out of the agent

| Layer | Checks | On failure |
|---|---|---|
| Request (`QueryRequest`) | Types, lengths, enums, year order; unknown fields rejected | `422` |
| Tool arguments (`SearchPlan`) | Slots typed; `advanced` may not carry what has a slot (phases, dates, study type...) | Sent back to the agent |
| Compile | Structured fields merged into slots; a comparison of values other than the user's field is rejected | Sent back |
| Fetch | API rejects the query, or nothing matches | Sent back (5 fetches at most) |
| Chart (`ChartPlan`, then the output validator) | The chart can be drawn; it fits the fetched data (field present, no stacking of multi-valued fields, time axis on the searched date); it shows the breakdown the plan said the question asks for; an unsupported breakdown must be refused | Sent back (3 retries), then the request fails |
| Response (`QueryResponse`) | Schema, every encoded field in every row, chart-type requirements; Vega-Lite spec validated against the official schema in tests | Error, never a malformed answer |

### 8. Structured outputs, never free text

The agent ends only through typed final-result tools: `ChartPlan` or `Unanswerable`. The response
itself is built by code from the chart plan and the trial records, so its structure cannot drift.
The model's own prose (its rationale) is kept in `meta.chain`, labelled as the agent's;
`meta.interpretation` is written by code from what was actually searched.

### 9. Improving the system from evidence

There is no training loop; improvement is a deliberate feedback loop:

1. Evals and adversarial reviews expose a failure (`trace.json` and `metrics` show what the agent
   did on every query).
2. Classify it: a broken **contract** (code was wrong, e.g. a conflicting field intersected) is
   fixed in a deterministic layer; a **judgement** error is fixed with general skill guidance,
   never a rule for one question; a **missing capability** becomes an honest refusal until built.
3. Rerun the affected cases live, and the unit tests.

Examples from the evals: dates cited exactly as written, the user's fields winning over the
question text, regions limited to their countries, shares computed by code, enrollment bins of
equal width, scatter plots once a second numeric field existed.

### 10. Evals that resist bias and overfitting

- **Cases from different sources:** the brief's examples, structured-field combinations, realistic
  users (typos, brand names, vague or slangy wording, regions, shares), refusals (advice, efficacy,
  made-up drugs, prompt injection), multi-step questions, and adversarial cases written by a
  reviewing agent that set out to break the system.
- **Tagged coverage:** every case is tagged by question class and input type; untested tags show.
- **Correctness, not shape:** reference searches counted live (recall), allowed and forbidden chart
  labels, the executed filters, citations checked against the live record, and API recounts.
- **Expect only what the question decides**, and honest refusals for known gaps.
- **No leakage:** skills never contain eval questions, and the agent never sees the cases.
- **Fix the design, not the test:** when a case failed, the question was which layer was wrong;
  checks that would reject correct answers were dropped rather than tuned to pass.

### 11. Deterministic layers, named

`request validation → plan (intent) → merge user fields → resolve names → compile query → fetch
(one data version, every page) → profile → chart validation → build (count, cite, label) → meta`.
Each layer has its own module and tests, so a failure points at one place.

### Trade-offs at a glance

| Choice | Cost |
|---|---|
| Fetch every matching trial | Broad questions are slower (tens of thousands of trials) |
| Complete `nct_ids` on every value | Larger responses: median about +27 KB; the network and scatter examples are under 1 MB |
| Typed slots instead of free API syntax | Rare filters go through `advanced`, validated only by the API (flagged in meta) |
| Standard name only when it dominates (≥50% of sampled trials) | Brands indexed under mixed terms may not expand; never expands to a co-tested drug |
| Study type defaults to all studies | Matches clinicaltrials.gov; "trials" includes observational studies unless asked otherwise |
| Skills instead of retrieval | Curated by hand; fits this domain, would not fit a large unstructured corpus |
| One run per eval case | Model choices can vary between runs; repeats are listed under limitations |
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

- **Building it:** developed with Claude Code (Anthropic) as a pair programmer. It wrote most of
  the code, tests, skills, eval cases and documentation, in small steps I reviewed. The
  decisions below were mine: I either proposed them or chose them from options it laid out.
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

### Decisions I made, and why

**Frontend demo**
- A minimal web page shaped around the brief, not a full app: the brief makes a frontend optional
  and puts the structured output first, so the page exists to *show* the output (response JSON,
  citations, opening saved example runs without an API key).

**Evals: from "does it pass?" to "is it right?"**
- Standardise the evals so each check states what it measures and passes or fails on its own:
  results have to be trackable, not a single opaque score.
- Review the evals with two agents holding a real conversation (one questioning, one defending)
  instead of one-shot answers, which stay shallow. They could run subsets of cases and add new
  ones, but not change the eval structure or the code they were judging.
- Fix the evals before the bugs: a pass has to mean the answer is right before a fix can be
  trusted. This moved the score from 60/62 (mostly checking shape) to 53/72 with real checks,
  then back up through actual fixes.

**Validation and guarantees**
- No hooks: checks in the tool code and output validator already run on every call and the agent
  cannot skip them, so hooks would add structure, not safety.
- Guard against overfitting: skill examples must not contain eval questions (a test enforces it),
  fixes must be general contracts rather than rules for one case, and brittle checks (such as "no
  digits in titles") were dropped.

**Searching: the design change**
- Resolve drug and condition names through the registry's own vocabulary (MeSH) before searching,
  instead of relying on the model's knowledge: look up how the registry indexes a name, search
  under both, consolidate, and keep the user's name as the label.
- Then step back: the string-level fixes were patching one design flaw, the agent writing raw API
  queries. The agent now states what the question means in typed slots and code builds the query
  ([design note](docs/design/search-intent.md)).
- The country list for regions is read from the registry at run time, because it changes.
- Mine the API for unused fields, and add only those that close real gaps (study design, duration
  for scatter plots); shares came from a missing feature, not missing data.

**Output**
- Check the output against the brief's own examples, change the format first, document it after.
- Include the complete list of trials behind every value, after measuring the overhead (median
  +27 KB per response): the deep-citations bonus asks for references to the underlying records.
- Commit the OpenAPI schema as well as serving `/docs`, since a reader may not run the server.

**Working method**
- Isolated worktrees for parallel or risky work, merged into `main` and then removed.
- Pause or stop work when the direction was unclear; close open items one at a time.

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
