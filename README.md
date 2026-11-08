# Cheiron: from a clinical-trials question to a chart with sources

Cheiron answers a natural-language question about clinical trials with one visualization: a
structured spec (type, title, encoding, data) and metadata, built from ClinicalTrials.gov API v2
data, with every value traceable to the trial records behind it.

One principle shapes the whole design: **a language model decides what the question means, and
plain code does everything that can be checked.** The model reads the question, plans the search,
and chooses the chart. Code fetches the trials, counts them, cites them, and writes the response.
The model never produces a number, so it cannot invent one. The rest of this README explains
where that line sits, why, and how the evals were used to move it.

Contents: [Running it](#running-it) · [What happens to a question](#what-happens-to-a-question) ·
[Design decisions and trade-offs](#design-decisions-and-trade-offs) · [How it is tested](#how-it-is-tested) ·
[Limitations and next steps](#limitations-and-next-steps) ·
[What I would build next](#what-i-would-build-next) · [Request and response schema](#request-and-response-schema) · [Use of AI tools](#use-of-ai-tools)

## Running it

```bash
cp .env.example .env          # set OPENAI_API_KEY; CHEIRON_PLANNER_MODEL=openai:gpt-5.4
uv sync
PYTHONPATH=src uv run uvicorn cheiron.api.app:app --port 8765
```

`PYTHONPATH=src` works around iCloud Drive hiding the virtualenv's `.pth` file; it is not needed
outside iCloud.

A question runs as a background task, because fetching every matching trial can take from
seconds to a minute. Submit it, then poll until `status` is `succeeded` or `failed`:

```bash
curl -s -X POST localhost:8765/queries -H 'content-type: application/json' \
     -d '{"query": "How has the number of trials for this drug changed over time?", "drug_name": "Pembrolizumab"}'
curl -s localhost:8765/queries/<task_id>
```

- `http://localhost:8765/` is a small web page that renders any answer and its sources.
- `http://localhost:8765/docs` is the interactive API reference.
- [`examples/`](examples/) holds five real requests and the exact JSON the service returned.
- `uv run pytest` runs the 261 unit tests; they need no API key.

## What happens to a question

The rest of the design is easiest to follow through one real question:
`{"query": "Compare phases for Ozempic vs Mounjaro trials"}`.

1. **The agent states what the question means.** It writes a search plan with two steps, one per
   compared drug: `{"label": "Ozempic", "drugs": ["Ozempic"]}` and
   `{"label": "Mounjaro", "drugs": ["Mounjaro"]}`. It writes no API syntax.
2. **Code resolves the names.** The registry does not map these brand names to their drugs: a
   search for "Ozempic" finds 104 trials, "semaglutide" finds 799. Code samples the trials each
   name matches, sees that 43 of 50 Ozempic trials are indexed under the MeSH term *semaglutide*
   (and 32 of 40 Mounjaro trials under *tirzepatide*), and searches both names.
3. **Code compiles and fetches.** Each step becomes a ClinicalTrials.gov query
   (`query.intr=("Ozempic" OR "semaglutide")`), and every matching trial is fetched, all on one
   version of the registry's data.
4. **The agent sees a profile, not the records.** For each field, the profile lists the number of
   distinct values, the trials with no value, and the top values with their trial counts. From
   it, the agent chooses a grouped bar chart of `phase` by compared side.
5. **Code checks the chart against the data and builds it.** Code counts distinct trials per
   phase and side (1,111 trials in all), attaches each bar's sources, adds display names
   (`PHASE2` → "Phase 2"), and writes the metadata, including both name expansions and why they
   were made.

The response is in [`examples/2-comparison`](examples/2-comparison/response.json) for a
similar question. Before step 2 existed, this question was answered from 144 trials, about 13% of
the relevant ones, and the evals passed it. That failure is behind several decisions below.

## Design decisions and trade-offs

The decisions follow the path a question takes.

### 1. The model interprets; code computes

Language models are good at interpreting a question and poor at reliable arithmetic over
thousands of records. The work is split along that line. The agent handles the parts that need
judgement: what is being asked, whether a second search is needed, which chart answers it, and
whether registry data can answer it at all. Code handles fetching, counting, citing, labelling and
the metadata.

Two things follow. Every number in a response is reproducible from the saved trial records. And a
model error can make the answer wrong in *meaning*, but never wrong in *arithmetic* or sourcing,
which narrows where errors can come from and lets the evals target interpretation.

*Cost:* the agent can only express what the plan and chart models allow, so a new capability
(percentages, scatter plots) needs code, not a prompt change.

### 2. One agent with tools, not a pipeline of agents

The first version was a pipeline: a search-planner agent, then code, then a chart-planner agent.
I replaced it with one agent and four tools: `fetch_data` (code runs a search plan),
`describe_data` (the profile of what was fetched), `load_skill` and `read_reference`.

The pipeline could not serve two kinds of question:

- **Multi-step questions** such as "the sponsor with the most melanoma trials, and its trials per
  year". The second search depends on what the first found, so the planner has to see results
  before it can finish. A one-way pipeline cannot loop back.
- **Questions whose right chart depends on what the search found.** A separate chart planner
  would not know why the search was shaped the way it was. One agent keeps the question, the
  search and its results in one reasoning context.

The agent may fetch up to five times, and each fetch is kept in `meta.chain` with the agent's
reason, so intermediate findings ("NCI leads melanoma with 205 trials") can be checked. Code
enforces the order: no chart is accepted before data has been fetched.

*Cost:* one context carries both jobs. Section 5 keeps that context small.

### 3. The agent states intent; code builds the query

This decision went through three versions, and the evals drove each change.

| Version | What the agent wrote | Why it changed |
|---|---|---|
| 1 | A typed plan with fixed fields | Fixed fields decided in advance what could be asked. I replaced them with a thin plan, to add structure only where real questions showed it was needed |
| 2 | ClinicalTrials.gov query syntax, checked by code | Wide coverage, but recall depended on what the model happened to know. The evals found wrong answers that passed: brand names searched instead of drugs (13% of the trials), a structured field intersected with a conflicting question term (melanoma trials that also mention lung cancer), regions charting other continents. Each fix meant code parsing strings the model wrote |
| 3 (current) | **What it means**, in typed slots: drugs, conditions, lead sponsors, countries or a region, phases, statuses, study type, years, enrollment | — |

In version 3, code turns the slots into the query, and the rules live in one place:

- **Names are resolved against the registry, not the model's memory**, as in step 2 of the
  example. Only the term on at least half of the sampled trials is added, so a drug co-tested in a
  minority of trials is never pulled in. A name that is itself an index term is never expanded.
  Searches stay text searches, because not every trial carries MeSH terms (596 semaglutide trials
  are indexed; 799 mention it).
- **The user's structured fields win.** They fill the same slots, so a conflict is a comparison of
  two values rather than a string parse. The field replaces the question's term, and the metadata
  says so.
- **Comparison sides stay apart.** If resolution would make two sides search the same thing
  (Ozempic and Wegovy are both semaglutide), those sides keep their literal names and a warning
  explains why.
- **Regions expand into countries from the registry's live country list**, so the list stays
  current, and the chart shows only those countries.
- **One rule for study type:** all studies, unless the question asks for interventional or
  observational ones. That matches what clinicaltrials.gov returns.

Version 3 keeps version 2's coverage through `advanced`, an escape hatch for a filter no slot
covers (for example randomised design). It is validated only by the API and shown to the reader.
The move from version 2 to 3 took the evals from 55 to 70 of 72. The full reasoning is in
[docs/design/search-intent.md](docs/design/search-intent.md).

*Alternatives rejected:* query templates per question type are accurate but break on any question
they did not foresee. Fine-tuning needs labelled data this project does not have, and it would
hide the rules inside weights, where they cannot be read or tested.

### 4. Every step is validated by code before it is used

Instructions in a prompt are requests; code on the execution path is a guarantee. Every place the
agent's output enters the system is checked, and a failure goes back to the agent with the reason
so it can correct itself.

| Where | What is checked | On failure |
|---|---|---|
| Request | Types, lengths, enum values, year order; unknown fields rejected | `422` to the client |
| Search plan | Typed slots; `advanced` may not carry anything that has a slot (phases, dates, study type) | Back to the agent |
| Compile | The user's fields against the plan; a comparison of values other than the user's field | Back to the agent |
| Fetch | The API rejects the query, or nothing matches | Back to the agent (at most 5 fetches) |
| Chart plan | The chart can be drawn; it fits the data fetched (the field has values, multi-valued fields are not stacked, the time axis uses the searched date); it shows the breakdown the plan said the question asks for | Back to the agent (3 retries), then the request fails |
| Response | The published schema, every encoded field in every row; the Vega-Lite spec is validated against the official schema in tests | An error, never a malformed answer |

One check deserves a note. The plan states the breakdown the question asks for ("by phase", "by US
state"), and the chart must show it. A breakdown the data cannot provide must be answered with a
refusal. Before this check, "where in the US … by state" was answered with a chart of countries,
titled "by state".

The agent ends only through typed final results, a `ChartPlan` or an `Unanswerable` reason, never
free text. Its own explanation is kept in `meta.chain` and labelled as the agent's;
`meta.interpretation` is written by code from what was actually searched.

### 5. The agent sees metadata, not records

A broad question can match tens of thousands of trials. The agent never sees them. `fetch_data`
returns only totals and what was searched. `describe_data` returns a profile: for each field, the
distinct values, the trials with no value, the top ten values with trial counts, whether a trial
can have several values, ties at the top, and numeric ranges. For the heart failure example, the
profile is 10 KB and the trial records it summarises are 9 MB.

That is all the agent needs to choose a chart: whether there is enough data, which fields are
filled, how many categories there are. The records stay on disk (`data/queries/<id>/fetch-N/`) for
the code that counts and cites them.

### 6. Knowledge comes from skills read on demand, not retrieval

The agent needs to know the ClinicalTrials.gov API: 24 record modules, 41 enums, every search area
and parameter. That knowledge is small, structured and authoritative, so I organised it as
**skills** in the Agent Skills format instead of indexing it in a vector database:

- `ctgov-search` is in the prompt (about 3,100 tokens): the procedure, the slots, rules checked
  against the live API, and worked examples. Its references (about 110 KB in all) are generated
  from snapshots of the official API documentation, and the agent reads one only when a table row
  says when ("read `enums.md` when you need an enum's allowed values").
- `chart-planning` (about 1,700 tokens) is loaded only once data has been fetched: a default chart
  for each question class, the known traps, and references for networks and registry statistics.

Retrieval by similarity can return the wrong chunk, or miss the right one, and the failure is
silent. With an index, the agent decides what to read, the trace records each read, and the
references are exact copies of the official documentation. A version check warns when the live API
moves past the documented version.

To keep the skills reliable, tests enforce the Agent Skills spec (size limits, references linked
from the skill), validate every example as a real plan or chart, and fail if a skill teaches an API
parameter the code does not accept. Each fact in a skill was checked against the live API with the
numbers quoted. No skill may contain an eval question (also a test), so the evals measure
judgement rather than copying.

*Cost:* the skills are curated by hand. That works for one well-documented API; it would not scale
to a large, unstructured corpus, where retrieval is the better tool.

### 7. Counts are exact, and every value shows its sources

- **Every page of every search is fetched.** Sampling would distort rankings and trends, and the
  registry is small enough to fetch exactly (the largest eval question fetched about 20,000
  trials). All steps run on one version of the registry's data, which refreshes daily. If it
  changes mid-fetch, the fetch is repeated.
- **Sources are exact.** Each bar, time bucket, bin, node, edge and scatter point lists every trial
  behind it (`nct_ids`), and details the first few in `citations`: the exact text from the API
  record (dates as written, such as `"2018-03"`), the field it came from, and the trial's title.

*Cost:* broad questions are slower, and responses are larger. The complete trial lists add a median
of 27 KB per response, and the largest examples are just under 1 MB.

### 8. The output speaks a frontend's language

The encoding uses Vega-Lite's vocabulary (`nominal`, `ordinal`, `temporal`, `quantitative`;
`x`, `y`, `color`, `xOffset`), which is precise enough that a renderer does not have to guess,
and each response also carries a ready Vega-Lite spec. Networks use the NetworkX node-link format.
Coded values keep the registry's codes in the data, so sorting and citations stay exact, while
`labels` gives each code its display name from the registry's own enum definitions.

### 9. The system improves from its failures, in code

Nothing in the system is trained. It improves through a deliberate loop:

1. An eval or a review exposes a failure. Every query saves a trace of what the agent did and
   metrics on time, tokens and tool calls, so a failure can be read, not guessed.
2. The failure is classified, and the fix goes to the layer that was wrong:
   - a broken **contract** (code combined two terms it should have replaced) is fixed in a
     deterministic layer;
   - a **judgement** error is fixed with general guidance in a skill, never a rule for one
     question;
   - a **missing capability** becomes an honest refusal until it is built.
3. The affected cases are rerun live, with the unit tests.

Evals drove these changes: citing dates exactly as written, the user's fields winning,
regions limited to their countries, equal-width enrollment bins, percentages computed by code, and
scatter plots once trial duration became available.

## How it is tested

The unit tests check the code with fake models and a fake registry. The evals check the whole
system against the real model and the real ClinicalTrials.gov API, because the failures that matter
most here (a search that misses most of the relevant trials) only appear with real data.

### What the evals check

There are 72 cases in six suites, one of them adversarial. Each case has a one-line intent,
tags for its question class, and declarative expectations. The checks were designed so that a
well-formed but wrong answer fails:

- **Recall:** a hand-written reference search is counted live at grading time, and the answer must
  contain at least 80% of its trials. This is the check that exposed the brand-name problem.
- **Labels:** the charted categories must stay within what was asked (`$EUROPE` for a European
  question), avoid what must not appear (placebo as a drug), and the title must not claim a
  breakdown the system cannot chart.
- **Filters:** the searches that actually ran must contain, or must not contain, given terms (for
  example `COMPLETED` for "completed each year").
- **Citations:** every excerpt must be in the saved trial record, and a sample must match the live
  record.
- **Recounts** of the largest bars against the API, count sanity, the response schema, and honest
  refusals that name the missing field.

### Guarding against bias and overfitting

- **The cases come from different sources:** the brief's own examples, structured-field
  combinations, realistic users (typos, brand names, vague wording, regions, percentages), refusals
  (advice, efficacy, made-up drugs, prompt injection), multi-step questions, and cases written by an
  adversarial reviewing agent whose job was to break the system.
- **Tags show coverage**, including the categories nothing tests yet.
- **No leakage:** the agent never sees the cases, and a test fails if a skill contains an eval
  question. When one slipped in during development, that test caught it.
- **Expectations cover only what the question decides**, so a correct answer is not failed for a
  different but valid chart.
- **The design is fixed, not the test.** When a case failed, the question was which layer was
  wrong. Checks that would have rejected correct answers were dropped rather than tuned.

### Results so far

| Stage | Result |
|---|---|
| First checks (mostly shape) | 60/62 passing, but several passes were wrong answers |
| Checks for correctness added, adversarial cases added | 53/72: the wrong answers now failed |
| Conflicting fields and lead sponsor fixed | 55/72 |
| Typed intent compiled by code | 70/72 |
| Percentages, design fields, scatter plots | 72/72 |

The 72/72 report combines live reruns of the cases each change affected; a single full rerun is
still to do. Each case also runs once, so a model choice that varies between runs can pass by
chance; see the limitations.

### Running the evals

With the service on port 8765:

```bash
uv run python evals/run.py                         # every case
uv run python evals/run.py --suite=brief,refusals  # some suites
uv run python evals/run.py --only=b3,m1            # some cases
uv run python evals/run.py --regrade               # re-check saved answers, no service calls
uv run python evals/run.py --coverage              # what the cases cover, no runs
```

How to add a case, every expectation key, and where outputs are stored are in
[`evals/README.md`](evals/README.md). Run results go to `evals/results/` (not in git), and each
answer links to the query's full saved output in `data/queries/<task_id>/`.

## Limitations and next steps

What is not done, roughly in the order I would do it:

1. **Investigators and trial sites are not available.** Networks of investigators or sites, and
   breakdowns by US state, city or facility, are refused with the reason. The API has the fields,
   but fetching them for every question would triple response sizes, and investigator names are
   noisy ("Pfizer CT.gov Call Center" appears as a person). Next: fetch site fields only when a
   question needs them, and clean investigator names against a list.
2. **Sponsor aliases depend on the model.** The registry has no canonical sponsor names: "MSD"
   matches six small MSD entities, not Merck Sharp & Dohme LLC, so the name resolution that works
   for drugs does not work for sponsors. The skill tells the agent to write the registered name.
   Next: an alias table built from the registry's lead-sponsor names.
3. **Network nodes are not normalised beyond spelling.** Names that differ by case or punctuation
   are merged, and placebo is excluded, but "Metformin" and "Metformin Hydrochloride" are separate
   nodes, and procedures can appear among drugs. Next: key nodes by their MeSH term.
4. **Evals run each case once, and the report is overwritten.** Next: three runs per case with a
   pass rate, a history of runs, a committed baseline, and a check of the agent's intent slots
   (`meta.filters_applied` already carries them).
5. **Drug classes** ("GLP-1 agonists") have no registry field; the agent expands them into member
   drugs from its own knowledge.
6. **Scatter plots** cover enrollment against duration only, and duration exists only for finished
   trials.
7. **One process, tasks in memory.** Task status is lost on restart (saved outputs remain) and is
   not shared between workers. Next: a persistent task store.

## What I would build next

The limitations above are fixes to the current design. The larger step is to make the system
improve itself in a controlled way, so that each failure found in production makes the next answer
better without anyone editing code.

### A reinforcement-style feedback loop over configuration

Today the knowledge that decides most outcomes is spread across code and skill text: the
name-resolution thresholds (`RESOLVE_SAMPLE`, `RESOLVE_SHARE` in `workflow/intent.py`), region
membership (`REGION_MEMBERS`), display names the registry lacks (`FALLBACK` in
`visualize/labels.py`), arms that are not interventions (`NOT_AN_INTERVENTION`), the default chart
for each question class and the known traps (the chart-planning skill), and the failure
categories the evals use (`TAGS`). Changing any of them means a code change.

The next version would move each of these into a versioned configuration file with a strict
schema, and add a second agent whose only job is to propose changes to those files:

1. **Signals.** Failed eval cases, user feedback (next section) and traces are collected as
   evidence, each tied to the configuration version that produced the answer (recorded in `meta`).
2. **Classification.** Each failure is classified in a fixed taxonomy (contract, judgement,
   capability, data) and a fixed set of characteristics (field, question class, entity type), so
   failures can be counted and grouped instead of read one by one.
3. **Proposal.** The improvement agent proposes a change only to configuration, never to code: for
   example, a sponsor alias, a region member, a new default chart for a question class, or a
   threshold. Each proposal must validate against the file's schema and cite the failures it
   addresses.
4. **Gate.** A proposal is accepted only if the unit tests pass, the evals do not regress, and it
   improves a held-out set of cases the improvement agent has never seen. That last condition is
   what keeps the loop from overfitting to its own evidence. A person approves the merge.
5. **Rollback.** Configurations are versioned, so a change that hurts can be reverted, and every
   answer records which version produced it.

This is reinforcement learning in its feedback structure, not in its mechanism: eval results and
user feedback act as the reward, configuration changes are the actions, and the gate decides which
changes are kept. No model weights change, so every improvement stays readable, testable and
reversible.

### User feedback as evidence

A `POST /queries/{task_id}/feedback` endpoint would let a user flag an answer with a fixed reason
(wrong trials searched, wrong count, wrong chart, missing data, wrong citation), point to the data
point concerned, and add a comment. Feedback is stored with the query's trace, so the exact search,
profile and chart behind the complaint can be replayed. Reviewed feedback becomes either a new eval
case (split between the development and held-out sets, so it cannot be overfitted) or evidence for
a configuration proposal.

### Automatic API version updates

Updating to a new ClinicalTrials.gov API version is manual today: run
`scripts/refresh_ctgov_docs.py`, rebuild the skill references with `scripts/build_ctgov_skill.py`,
review the diff, and bump `SNAPSHOT_API_VERSION`. The service only logs a warning when the live API
moves past the documented version.

A scheduled job would do this instead: detect the new version (`refresh_ctgov_docs.py --check`
already exits with an error when it changes), refresh the snapshots, regenerate the references,
run the unit tests and the evals, and open a pull request with the documentation diff and the eval
report. A contract test would fail the run, and flag it for a person, whenever a field, enum value
or parameter the code depends on disappears.

### Leaner skills, measured

The skills were written rule by rule as failures appeared. The traces already record which
references the agent reads, so each part of a skill can be measured: rules no eval depends on can
be removed, and rules that code can enforce can move into code, as happened with study type. Each
remaining rule would get an eval case that fails without it. A new skill version would be adopted
only if it does at least as well on the held-out cases with fewer tokens. A smaller skill leaves
the agent less to misread, which is where accuracy gains are left at this point.

## Request and response schema

The machine-readable schema is committed at [`docs/api/openapi.json`](docs/api/openapi.json)
(regenerate with `uv run python scripts/export_openapi.py`; a test fails if it drifts from the
code) and served at `/openapi.json`, `/docs` and `/redoc` while the service runs. This section
covers what the schema alone does not.

### Endpoints

| Method | Path | Body or result |
|---|---|---|
| `POST` | `/queries` | `QueryRequest` → `202` with a task (`Location: /queries/{task_id}`); `422` if the request is invalid |
| `GET` | `/queries/{task_id}` | The task: `status` (`queued`, `running`, `succeeded`, `failed`), `progress` (stage and message), `result` (a `QueryResponse` once succeeded), `error` (an `ErrorResponse` if failed). `404` once forgotten: tasks are kept 24 hours, in memory |
| `GET` | `/health` | `{"status": "ok"}` |

### Request: `QueryRequest`

| Field | Type | Required | Validation |
|---|---|---|---|
| `query` | string | yes | 3–500 characters |
| `drug_name` | string | no | 1–200 characters |
| `condition` | string | no | 1–200 characters |
| `sponsor` | string | no | 1–200 characters; the **lead** sponsor |
| `country` | string | no | 2–100 characters; a country with a trial site |
| `trial_phase` | list of `EARLY_PHASE1`, `PHASE1`, `PHASE2`, `PHASE3`, `PHASE4`, `NA` | no | at least one |
| `recruitment_status` | list of `NOT_YET_RECRUITING`, `RECRUITING`, `ENROLLING_BY_INVITATION`, `ACTIVE_NOT_RECRUITING`, `COMPLETED`, `SUSPENDED`, `TERMINATED`, `WITHDRAWN`, `UNKNOWN` | no | at least one |
| `start_year`, `end_year` | integer | no | 1900–2100, `start_year` ≤ `end_year`; an inclusive range on the trial's **start** date |

Unknown fields are rejected, so a misspelt field cannot be silently ignored. Structured fields
always apply, and when the question text disagrees with one, the field wins (section 3 above).

### Response: `QueryResponse`

```
QueryResponse
├── visualization   one chart or network; its shape depends on `type`
│   ├── type        bar_chart | grouped_bar_chart | stacked_bar_chart | time_series | histogram | scatter_plot | network_graph
│   ├── intent      change_over_time | ranking | distribution | magnitude | part_to_whole | correlation | spatial | relationship
│   ├── title
│   ├── encoding    which data field goes on which visual channel
│   └── data        rows (charts) or {nodes, edges} (networks), each with its sources
├── meta            how the answer was computed
└── vega_lite       the same chart as a ready-to-render Vega-Lite v5 spec (null for networks)
```

#### Channels in `encoding`

Charts use the channels `x` and `y`, and optionally `color` (a series), `xOffset` (grouped bars
side by side) and `x2`. Each channel has:

| Key | Meaning |
|---|---|
| `field` | The key in each data row |
| `type` | `quantitative` (numbers), `nominal` (categories), `ordinal` (ordered categories), `temporal` (ISO dates) |
| `title` | The axis or legend title |
| `sort` | `"-y"` for largest first, or an explicit order (phases in clinical order) |
| `timeUnit` | `utcyear` on time axes: each row's date is 1 January of its year |
| `scale` | `"log"` where values are heavily skewed (enrollment in scatter plots) |
| `labels` | The display name of each coded value, e.g. `{"PHASE1": "Phase 1"}`. Rows keep the codes; show the label when there is one |

The fields a chart can use are `phase`, `start_year`, `completion_year`, `overall_status`,
`lead_sponsor`, `sponsor_class`, `condition`, `intervention`, `intervention_type`, `country`,
`study_type`, `allocation`, `masking`, `primary_purpose`, `enrollment`, `duration_months`, and
`group` (the side of a comparison).

#### Data rows by chart type

Every row has its encoded fields, `citations` and `nct_ids`.

| `type` | One row per | Value fields |
|---|---|---|
| `bar_chart` | category | `<x field>`, `trial_count` |
| `grouped_bar_chart`, `stacked_bar_chart` | category and series value | `<x field>`, `<series field>`, `trial_count` |
| `time_series` | year, including empty years as 0 | `start_year` or `completion_year` as `"2015-01-01"`, `trial_count` |
| `histogram` | enrollment bin | `enrollment_range` (a label such as `"50–99"` or `"10,000+"`), `enrollment_from`, `enrollment_to` (**exclusive**; `null` means no upper bound), `trial_count` |
| `scatter_plot` | trial | `enrollment`, `duration_months` (start to actual primary completion), optional series field |
| a bar chart or time series showing shares | as above | also `percent` (0–100) and `of_trials` (its denominator); `y` charts `percent` |

Counts are of distinct trials. A field that can hold several values per trial (phase, condition,
intervention, intervention type, country) counts the trial once per value, so bars can add up to
more than `meta.trials_analyzed`; `meta.assumptions` says so when it applies.

#### Networks

`data` is a NetworkX node-link graph (`networkx.node_link_graph(data, edges="edges")` reads it):

- `nodes`: `id`, `label`, `group` (the node kind, such as `lead_sponsor`), `size` (trials with this value)
- `edges`: `source`, `target` (node ids), `weight` (trials that have both values)
- `encoding` names these keys and gives `group_labels` for display.

#### Sources

| Key | Meaning |
|---|---|
| `nct_ids` | Every trial counted in this data point, complete and sorted |
| `citations` | The first few of those trials in detail: `nct_id`; `excerpt`, the exact text or value from the API record that placed the trial here; `field`, the API field path it came from; `title`, the trial's brief title as in the API, given once per trial within a data point |

Answers built from registry-wide statistics (such as "which drug has the most trials?") have counts
but no per-trial sources, and `meta.warnings` says so.

#### `meta`

| Field | Meaning |
|---|---|
| `interpretation` | What was searched, in plain words, written by code from the searches that ran |
| `request_filters` | The structured fields the user sent, as sent |
| `filters_applied` | `{"steps": [...]}`: each search's exact API parameters, what the agent asked for (`intent`), and names also searched under the registry's name (`searched_as`) |
| `assumptions` | Counting rules and decisions the reader needs: multi-valued fields, replaced terms, what a percentage is of |
| `warnings` | Values excluded, categories cut to the largest ones, a partial current year, samples |
| `units` | What each number counts, by data key |
| `total_trials_matched`, `trials_analyzed` | Matches at the source, and trials aggregated |
| `data_as_of`, `api_version`, `source` | The registry's data refresh time, the API version, `"clinicaltrials.gov"` |
| `chain` | Every fetch the agent made, in order, with its reason in the agent's words |
| `metrics` | Run time, tokens and tool calls |

#### Errors

`{"error": <code>, "message": <text for the user>, "details": {...}}`, where `error` is one of
`invalid_request`, `unsupported_query` (registry data cannot answer it: efficacy, advice, or a
breakdown by a field that is not available), `no_results`, `upstream_error` (ClinicalTrials.gov
failed) or `internal_error`.

## Use of AI tools

**Building it.** I built the project with Claude Code (Anthropic) as a pair programmer. It wrote
most of the code, tests, skills, eval cases and documentation, in small steps I reviewed. The
design decisions above were mine: I proposed them or chose them from options it laid out. The
turning points were:

- splitting the work between a model that interprets and code that computes, and replacing the
  two-agent pipeline with one agent and tools when multi-step questions needed to loop;
- organising the API knowledge as skills read on demand rather than retrieval;
- reviewing the evals with two agents in an actual back-and-forth (one questioning, one
  defending), because a single question-and-answer pass stayed shallow;
- fixing the evals before the bugs, so that a pass meant a correct answer;
- asking whether we were overfitting, which led to the leakage test and to dropping brittle checks;
- recognising that the string-level search fixes were patching one design flaw, and moving to
  typed intent with names resolved through the registry's own vocabulary;
- keeping hooks out, because checks on the execution path already guarantee what hooks would add;
- checking the output against the brief's examples and including complete trial lists after
  measuring their cost.

**Running it.** The query agent uses an OpenAI model, set by `CHEIRON_PLANNER_MODEL`.

**How correctness was checked.**

- 261 unit tests with fake models and a fake registry;
- live evals: 72 cases against the real model and API, as described in
  [How it is tested](#how-it-is-tested);
- every number quoted in a skill or in this README was checked against the live API or measured
  from saved outputs;
- the web page was checked with screenshots of real responses.
