# Evals

An eval is a test case with an expected outcome, run against the **live service** and checked
automatically. Unit tests (`tests/`) check the code with fakes; evals check the whole system:
the real model, the real ClinicalTrials.gov API, and the response a user would get.

```
evals/
  cases/          the test cases, one file per suite
  checks.py       the tag list and every check
  run.py          runs cases, checks answers, prints coverage by tag
  results/        raw responses + report.json (gitignored)
```

## A case

```json
{"id": "r22",
 "intent": "Question says lung cancer, structured field says melanoma: the field must win",
 "tags": ["input.structured", "input.conflict"],
 "request": {"query": "Show lung cancer trials by phase", "condition": "melanoma"},
 "expect": {"outcome": "answered", "chart": ["bar_chart"], "meta_mentions": "melanoma", "filters_exclude": "lung"},
 "note": "optional context"}
```

- `intent`: one line on what the case is there to test.
- `tags`: from the fixed list in `checks.py` (`TAGS`). An unknown tag stops the run.
- `request`: sent as-is to `POST /queries`.
- `expect`:
  - `outcome`: `answered`, `refused` or `either`. This one is required.
  - `chart`: the allowed chart types.
  - `x`: the field the x axis must use.
  - `meta_mentions`, `filters_exclude`, `data_excludes`: text that must or must not appear.

## Suites

| File | What it covers |
|---|---|
| `brief.json` | The brief's own example questions |
| `structured.json` | The structured request fields, alone or against the question text |
| `users.json` | Realistic user questions: typos, brands, vague wording, shares, known gaps |
| `refusals.json` | Must not answer: advice, efficacy, nonsense, made-up drugs, prompt injection |
| `multistep.json` | A later fetch depends on what an earlier one found |

## Checks (run on every case; a check that does not apply passes)

| Check | Fails when |
|---|---|
| outcome | answered or refused differently from `expect.outcome` |
| format | the response does not match the published `QueryResponse` schema, or a chart has no Vega-Lite spec |
| chart | the chart type or x field is not the expected one |
| expectations | `meta_mentions` / `filters_exclude` / `data_excludes` are not met |
| counts | a bar exceeds the trials analysed, or a single-valued field sums to more than that |
| citations | a data point has no citations, or a quoted excerpt is not in the saved trial record |
| citations_live | a sample of citations does not match the live registry record |
| recount | the two biggest phase / status / sponsor-class bars differ from an API recount |

What the checks cannot tell you: the recount reuses the system's own search, so it proves the
counting, not that the search matched the question. Expected chart types are only set where
the question makes the right chart clear.

## Running

With the service on port 8765:

    uv run python evals/run.py                         # everything
    uv run python evals/run.py --suite=brief,refusals  # some suites
    uv run python evals/run.py --only=b3,m1            # some cases
    uv run python evals/run.py --regrade               # re-check saved responses, no service calls
    uv run python evals/run.py --coverage              # what the cases cover, no runs

Every run ends with a coverage table: for each tag, the number of cases, how many ran, how many
passed, and which ones failed. `NO CASES` marks tags nothing tests yet.
