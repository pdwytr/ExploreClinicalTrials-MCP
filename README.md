# Cheiron: from a clinical-trials question to a chart with sources

Cheiron answers a natural-language question about clinical trials with one visualization: a
structured spec (type, title, encoding, data) and metadata, built from ClinicalTrials.gov API v2
data, with every value traceable to the trial records behind it.

One principle shapes the whole design: **a language model decides what the question means, and
plain code does everything that can be checked.** The model reads the question, plans the search,
and chooses the chart. Code fetches the trials, counts them, cites them, and writes the response.
The model never produces a number, so it cannot invent one. It is built on published
standards (Agent Skills, Pydantic, the Financial Times Visual Vocabulary, Vega-Lite) rather than
private formats. The rest of this README explains where the line between model and code sits, why,
and how the evals were used to move it.

**Live demo:** the service is deployed at **https://cheiron-e7vsuq.fly.dev/**. Open it to ask a
question in the web page, or see the API reference at
[`/docs`](https://cheiron-e7vsuq.fly.dev/docs) (interactive, Swagger UI) and
[`/redoc`](https://cheiron-e7vsuq.fly.dev/redoc) (ReDoc). It runs on one Fly.io machine, so tasks
and saved outputs are lost when it restarts or is redeployed.

Contents: [Running it](#running-it) · [What happens to a question](#what-happens-to-a-question) ·
[Design decisions and trade-offs](#design-decisions-and-trade-offs) · [How it is tested](#how-it-is-tested) ·
[Limitations and next steps](#limitations-and-next-steps) ·
[What I would build next](#what-i-would-build-next) · [Request and response schema](#request-and-response-schema) · [Use of AI tools](#use-of-ai-tools)

## Running it

Requires Python 3.11+ and an OpenAI API key.

```bash
git clone https://github.com/pdwytr/cheiron.git && cd cheiron
cp .env.example .env          # set OPENAI_API_KEY; CHEIRON_PLANNER_MODEL=openai:gpt-5.4
```

With [uv](https://docs.astral.sh/uv/):

```bash
uv sync
uv run uvicorn cheiron.api.app:app --port 8765
```

Or with pip:

```bash
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e .
uvicorn cheiron.api.app:app --port 8765
```

Instead of a `.env` file, you can set `OPENAI_API_KEY` and `CHEIRON_PLANNER_MODEL` as environment
variables, which is how a hosting platform would supply them.

### The frontend

There is no separate frontend to build or start. The backend serves the web page itself: with
the server running, open **http://localhost:8765/**, type a question, add any filters, and the
page shows the chart, the numbers behind it and the trials each number cites. It is one file,
[`src/cheiron/web/index.html`](src/cheiron/web/index.html), and it draws charts with Vega-Lite
loaded from a CDN, so it needs internet access but no Node.js or `npm`.

### The API

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

### Built on published standards

I designed the system to the standard I would hold a production service to, and the most
deliberate part of that was to build on published standards instead of inventing formats. A
standard brings a specification other people already understand, tooling that validates against
it, and a reviewer who does not have to learn a private convention. Each one below is checked by
tests, not just followed by convention.

| Standard | Used for | Why this one | Enforced by |
|---|---|---|---|
| [Agent Skills](https://agentskills.io/specification) | Both skills (`ctgov-search`, `chart-planning`) | A documented format for giving an agent knowledge in layers: metadata, instructions, then references loaded only when needed. That is exactly the context discipline section 5 relies on | Tests check frontmatter, naming, size limits, that every reference is linked with when to read it, and that every example is valid |
| [Pydantic](https://docs.pydantic.dev) and [Pydantic AI](https://ai.pydantic.dev) | The request, the agent's tool arguments and final answers, the response | One typed definition serves as validation, the agent's tool schema and the API documentation. A structured answer that fails validation goes back to the model with the error, instead of breaking downstream code | The models themselves; the OpenAPI schema generated from them is committed and checked for drift |
| [Financial Times Visual Vocabulary](https://github.com/Financial-Times/chart-doctor/tree/main/visual-vocabulary) | Chart intent (`change_over_time`, `ranking`, `distribution`, `magnitude`, `part_to_whole`, `correlation`, `spatial`), plus `relationship` for networks, which the FT places under flow | It classifies charts by the question they answer rather than by their shape, which is how the chart-planning skill chooses: first what is being asked, then the chart. Deviation is not used yet, because no question class compares against a baseline | `Intent` enum in the response schema |
| [Vega-Lite v5](https://vega.github.io/vega-lite/) | The `encoding` vocabulary and the ready-to-render `vega_lite` spec | A declarative grammar with a published JSON schema: field types (`nominal`, `ordinal`, `temporal`, `quantitative`) and channels mean the same thing to every renderer, and a frontend can draw the chart with no custom code | Every generated spec is validated against the official Vega-Lite schema in tests |
| [OpenAPI](https://www.openapis.org) | The HTTP API | Generated by FastAPI from the Pydantic models, so the documentation cannot disagree with the code | Committed at `docs/api/openapi.json`, with a drift test |
| [NetworkX node-link format](https://networkx.org/documentation/stable/reference/readwrite/json_graph.html) | Network graphs | A graph format libraries already read (`networkx.node_link_graph`) | Tests read the output back with NetworkX |
| [MeSH](https://www.nlm.nih.gov/mesh/) (through the registry) | Resolving drug and condition names | The registry already indexes every trial under the National Library of Medicine's vocabulary, so it is the authoritative way to know what a name refers to | Section 3 |

The same production standard shows elsewhere: queries run as background tasks with progress, every
fetch is pinned to one version of the registry's data, every query saves a trace and metrics, and
the API reference the agent reads is versioned and checked against the live API. Where the system
falls short of production (tasks kept in memory, a single process), the limitations say so.

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
7. **One model, untested against others.** Every result here comes from GPT-5.4. The code accepts
   only OpenAI models today, although Pydantic AI supports most providers. Next: allow any
   provider, run the full eval suite on several models, and compare pass rate, latency and cost
   per question. Because the model only interprets and code does the rest, a smaller, cheaper
   model may do as well, and the evals are the way to find out.
8. **One process, tasks in memory.** Task status is lost on restart (saved outputs remain) and is
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

### Caching large fetches by registry data version

Most of a query's time goes into fetching trials, not into the model. In the full eval run the
median question took 8 seconds and the slowest 33, and a broad question moves megabytes (the heart
failure scatter fetched 7,406 trials, 9 MB of records). Popular questions repeat the same searches,
and the registry changes only once a day, so the same fetch is often repeated against identical
data.

The fetched trials would be cached, keyed by two things:

- **the compiled search**: the exact API parameters after resolution and the user's fields, in a
  canonical order, so two differently worded questions that compile to the same search share an
  entry;
- **the registry's data version**: the refresh timestamp from `GET /version`, which the pipeline
  already reads before and after every fetch.

The cache is indexed by data version. When the registry refreshes, every entry from the previous
version becomes invalid at once, which can never serve stale data and needs no per-entry expiry
rule. Name resolutions (the sampled MeSH terms) and the registry's country list would be cached the
same way.

Only the deterministic part is cached: the agent still interprets each question, so a cached fetch
cannot hide a change in interpretation. The cost is storage for the largest searches, and a first
query after each daily refresh that is no faster than today. A later step would reuse a broad
cached search for narrower questions by filtering the cached trials locally, but only for filters
code can apply exactly (phase, status, years), so counts stay identical to the API's.

### Richer chart planning

The chart-planning skill maps ten question classes to seven chart types, and each class has one
default. That covers the brief's examples, but some questions still get a weaker chart than they
deserve, because the right chart type does not exist yet or the skill gives no rule for choosing
between two acceptable ones:

- **"Where" questions get a bar chart**, though the `spatial` intent exists: a world map
  (choropleth) of trials per country would read faster. The data is already there; the builder and
  the response schema would need a geographic chart type.
- **Two categories over time** ("phases per year") are drawn as a time series with a series per
  phase, which tangles beyond four or five lines. A heatmap (year × phase, colour = trials) or small
  multiples (one panel per phase) would stay readable.
- **A number across categories** ("enrollment by phase") has no chart: a histogram shows one
  distribution, not several. A box plot per category would answer it from the per-trial values the
  builder already holds.

New chart types need the same work as the existing ones: a builder that counts and cites, schema
rules, and a section in the skill. The skill would also replace judgement with thresholds read from
the profile wherever a threshold is honest: more than five series on a time axis means small
multiples; a numeric field whose maximum is a hundred times its median gets a log scale; a ranking
with ties at the cut-off shows every tied value. Each new rule would come with an eval case that
fails without it, measured on the held-out set like any other skill change.

### Leaner skills, measured

The skills were written rule by rule as failures appeared. The traces already record which
references the agent reads, so each part of a skill can be measured: rules no eval depends on can
be removed, and rules that code can enforce can move into code, as happened with study type. Each
remaining rule would get an eval case that fails without it. A new skill version would be adopted
only if it does at least as well on the held-out cases with fewer tokens. A smaller skill leaves
the agent less to misread, which is where accuracy gains are left at this point.

### Production hardening

The service is built for correctness first. Before real users depend on it, I would harden three
things.

**Logging and tooling.** Modules log today with Python's standard `logging`, one logger each, and
each query's full trace is saved to its output folder. Next comes one logging setup for the whole
service: structured JSON lines carrying the task ID through every stage (request, intent, fetch,
chart, response), with timings, model token counts and the number of ClinicalTrials.gov calls, and
the API key and other secrets redacted. Those fields would feed metrics and alerts: error rate,
latency per stage, model cost per query, and upstream API failures and retries.

**Validation and error handling for edge cases.** The request schema and the refusal paths cover
the cases the evals exercise. Next is a deliberate sweep of what they do not: empty or very long
questions, contradictory filters (a start year after the end year), drug or sponsor names that
resolve to nothing or to thousands of trials, ClinicalTrials.gov timeouts, rate limits and
malformed pages, the model provider being down or returning invalid output, and a task cancelled
or forgotten mid-run. Each would get a test that pins its behaviour, so every failure ends in a
clear `ErrorResponse` with a stable error code, never a stack trace or a task stuck in `running`.

**Load testing with 100 concurrent users.** The service has not been load tested. I would use
[Locust](https://locust.io/) to simulate 100 users submitting a realistic mix of questions (from
narrow ones that fetch a few trials to broad ones that fetch thousands) and polling their tasks,
and measure throughput, latency percentiles, error rate and memory. The likely limits, each of
which the test would confirm or rule out:

- **Rate limits upstream.** Every query fetches from ClinicalTrials.gov and calls the model
  provider, so both would throttle long before the server's CPU runs out.
- **Memory.** Tasks and their results live in one process's memory for 24 hours, and a broad
  question holds megabytes of records while it runs.
- **One process.** The in-memory task store means the service cannot yet run as several
  replicas behind a load balancer.

The fixes follow from what the test shows: a cap on concurrent tasks with a queue in front of
it, the fetch cache described above, and moving task state and outputs to shared storage (for
example Redis or a database for tasks and object storage for outputs) so the service can scale
out. The Locust scenario would then run in CI against each release to catch regressions.

**Query data that keeps growing.** Every query writes a folder to `data/queries/` and nothing
deletes it; only the in-memory task is forgotten after 24 hours. After development and the eval
runs, 373 queries take 1.4 GB, and about 95% of that is the raw trial records each fetch saves
(`fetch-<n>/trials/`). The request, response, metadata, trace, plans and profiles are small. So
the plan is to treat the two kinds of data differently:

- **Keep the small files; expire the raw trials.** The small files are what explains and replays
  an answer, so they are kept long term. Raw trial files are kept for a fixed window (say 30
  days), then deleted, unless the query was flagged through user feedback or became an eval
  case, which pins it.
- **Compress.** The JSON is written pretty-printed; gzip shrinks a typical trials file about
  6.5 times (2.8 MB to 0.42 MB).
- **Store each trial once.** Broad and repeated questions save the same trials again and again.
  Storing each record once, keyed by NCT ID and its last-update date, and having each fetch keep
  only the list of IDs it got, removes the duplication. This shares its storage with the fetch
  cache above.
- **Move off local disk.** Outputs go to object storage (S3, R2 or GCS) with lifecycle rules that
  apply the retention window automatically, and the metadata goes to a database, so queries can
  be searched and counted without reading folders. This is also what lets several replicas share
  outputs.
- **Watch it.** Storage used and growth per day become metrics with an alert, so a change that
  suddenly saves much more data is noticed.

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

How one question moves through them:

1. **`POST /queries` submits it.** The `QueryRequest` is validated first, so a bad request (an
   unknown field, `start_year` after `end_year`) gets a `422` before any work starts. A valid one
   returns `202` at once with a `task_id`, and the work runs in the background, because fetching
   every matching trial can take from seconds to a minute.
2. **`GET /queries/{task_id}` is polled** every few seconds until `status` is `succeeded` or
   `failed`. `progress` names the current stage: `queued`, `planning` (the model reads the
   question and plans the search), `fetching` (code calls ClinicalTrials.gov, with a trial
   count), `analyzing`, `building` (code counts, cites and builds the chart), `saving`, then
   `done` or `failed`. On success, `result` holds the `QueryResponse`: the `visualization` with
   every row citing its trials, `meta`, and the `vega_lite` spec. On failure, `error` says why,
   including an honest refusal for a question the service cannot answer.
3. **`GET /health`** is not part of answering a question; the host (Fly.io) calls it to check the
   service is up.

The web page at `/` is a client of the first two: it posts the question, polls the task, then
draws `vega_lite` and lists the trials behind each value. In `/docs`, "Try it out" calls the
endpoints from the browser.

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

The brief asks three things: which tools I used, how I checked correctness, and which parts I
designed deliberately versus generated and adapted. In short: Claude Code wrote most of the code,
I owned the design and the definition of "correct", and nothing was accepted because it looked
right.

### Tools

- **Claude Code (Anthropic)** was my pair programmer for the whole build: code, tests, skills,
  eval cases, documentation, and the Fly.io deployment files. I worked in small steps and reviewed
  each one.
- **Agents inside Claude Code** took over more of the testing as the codebase became reliable.
  They drilled the evals, hunted for bugs, and fixed minor ones on their own. One wrote eval cases
  whose only job was to break the system. Eval reviews ran as an actual back-and-forth between an
  agent questioning the results and one defending them, because a single question-and-answer pass
  stayed shallow.
- **OpenAI GPT-5.4** runs the query agent at request time
  (`CHEIRON_PLANNER_MODEL=openai:gpt-5.4`). Every eval result in this README comes from that
  model; I have not compared it with others.
- **Not AI:** the API knowledge the agent reads is not model-written. The skill's reference files
  are generated by a plain script (`scripts/build_ctgov_skill.py`) from snapshots of the official
  ClinicalTrials.gov documentation.

### What I designed, and what was generated

The line I held: I decided what the system is and what counts as a correct answer; the model
wrote most of what implements those decisions. I did not delegate design, and I kept a working
understanding of the codebase, so I could say why each part exists and where a failure
belonged before deciding how to fix it.

**Designed deliberately**, each one a choice I made or picked from options Claude laid out:

- **The split between model and code.** The model interprets the question; code fetches, counts,
  cites and writes the response, so the model never produces a number. Most other decisions follow
  from this one.
- **One agent with tools instead of a pipeline**, once multi-step questions needed to loop back.
- **Skills read on demand instead of retrieval** for the API knowledge, and their structure: what
  each skill covers, how its references are split, and which published standards its outputs must
  follow (Vega-Lite encodings, the Financial Times Visual Vocabulary for choosing a chart).
- **Typed intent compiled by code**, with names resolved through the registry's own vocabulary.
  This replaced a run of string-level search fixes. Each was plausible on its own; together they
  were patching one design flaw case by case.
- **The response contract:** every data row cites its trials, built on Vega-Lite and the
  Financial Times Visual Vocabulary rather than a private format.
- **What "correct" means in the evals:** recall against a hand-written reference search, live
  recounts and citation checks, and the rule to fix the evals before the bugs.
- **What not to build:** no hooks, since checks on the execution path already guarantee what
  hooks would add; and honest refusals instead of best guesses.

**Generated and adapted:**

- **Implementation and unit tests**, generated from my descriptions and reviewed step by step.
  When code drifted from the design, the design won and the code changed.
- **Skill rules**, written with Claude inside the structure I set, rule by rule as eval failures
  appeared.
- **Eval cases**: the brief's examples and my own scenarios, plus the adversarial agent's cases. I
  decided which expectations stayed, and dropped checks that would have failed correct answers.
- **The web page, README drafts, and the Dockerfile and `fly.toml`**, each checked by running it:
  screenshots of real responses for the page, a real query against the live deployment for the
  container.

### How I validated correctness

Every check is meant to fail a well-formed but wrong answer, because that is the failure an AI
assistant makes easiest to miss.

- **Structured, typed data at every boundary, for code and model alike.** Each component passes
  Pydantic models, not loose dicts or free text: the request (unknown fields are rejected), the
  ClinicalTrials.gov records as they arrive, the agent's tool inputs (a `SearchPlan`), the agent's
  final answer (a `ChartPlan` or an `Unanswerable`), and the response. Model output gets no
  exemption. If the agent returns a malformed plan, or a chart that does not fit the data actually
  fetched, code rejects it and sends the reason back for a retry, so a wrong format never reaches
  the user.
- **Manual testing.** I ran questions through the service and the web page myself, and came up
  with edge cases the brief does not mention, such as misspelt and brand drug names, vague
  wording, regions instead of countries, filters that contradict the question, made-up drugs, and
  questions outside the registry's scope.
- **261 unit tests** with fake models and a fake registry; they need no API key.
- **Contract tests:** every generated chart validates against the official Vega-Lite schema; the
  committed OpenAPI file fails a test if it drifts from the code; and a leakage test fails if a
  skill contains an eval question. That test caught one during development.
- **72 live evals** against the real model and API ([How it is tested](#how-it-is-tested)). The
  progression is the evidence that they test the right thing: the first checks, mostly of shape, passed
  60 of 62 cases, several of them wrong answers; adding correctness checks dropped that to 53 of
  72; design fixes brought it to 72 of 72. That last figure combines reruns of the affected cases
  and each case ran once, so it is not yet a single clean run.
- **Every number** quoted in a skill or in this README was checked against the live API or
  measured from saved outputs.

### What I watched for

Three habits of AI-assisted work showed up here, and most of the design history is me catching
them:

- **Patching symptoms.** Agents fixing bugs on their own sometimes hacked a fix for what was
  really a design issue. The string-level search fixes above are the clearest case: each made one
  failing case pass without asking why the cases failed. Minor fixes stood; when a fix was working
  around the design, I stopped it and redirected the agent to the actual problem.
- **Tests that pass on shape.** The first evals checked that an answer looked like a chart, so
  wrong answers passed. Making a wrong answer fail came before fixing anything.
- **Overfitting to the evals.** Asking whether we were tuning to the cases led to the leakage
  test, to dropping brittle checks, and to the held-out set in the plans above.
