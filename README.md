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

_To write._

## Design decisions

_To write._

## Limitations

_To write._

## Use of AI tools

_To write._

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
   - Optional expectations:
     - `chart`: the allowed chart types
     - `x`: the x-axis field
     - `meta_mentions`, `filters_exclude`, `data_excludes`: text that must or must not appear

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
