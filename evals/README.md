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
  - `filters_include` / `filters_exclude`: text that must / must not be in the searches that
    actually ran (`meta.filters_applied`), e.g. `"COMPLETED"`, `"semaglutide"`. Prefer these to
    `meta_mentions`, which also matches the model's own prose.
  - `meta_mentions`: text that must appear anywhere in `meta`.
  - `data_excludes`: text that must not appear in any charted row (labels or counts).
  - `labels_within` / `labels_exclude`: the charted categories (x values, a non-group series,
    network node labels) must all be in a list, or contain none of a list. Named sets such as
    `"$EUROPE"` are defined in `checks.py` (`REGIONS`).
  - `recall`: reference searches, written by hand as plain API parameters. Each is counted live at
    grading time (so it never goes stale), and the charted trials must contain at least 80% of
    what it finds (`"min"` overrides). `"match"` ties an entry to the compared side(s) whose label
    contains one of its words:
    `[{"match": ["ozempic", "semaglutide"], "search": {"query.intr": "semaglutide OR Ozempic"}}]`.
    Write references to be a fair subset of what the question asks for (e.g. a narrower date
    window), so that a correct answer always contains them.
  - `units_include`: words of which one must be in `meta.units` (e.g. a share question needs
    percent, not counts).
  - `refusal_mentions`: for `refused` cases, words of which at least one must be in the refusal
    message, so refusing for the wrong reason still fails (e.g. `["duration"]`).
  - Any other key stops the run (`EXPECT_KEYS` in `checks.py`), so a typo cannot silently skip a check.

## Suites

| File | What it covers |
|---|---|
| `brief.json` | The brief's own example questions |
| `structured.json` | The structured request fields, alone or against the question text |
| `grilled.json` | Cases from an adversarial review: things the system got wrong while the other suites passed |
| `users.json` | Realistic user questions: typos, brands, vague wording, shares, known gaps |
| `refusals.json` | Must not answer: advice, efficacy, nonsense, made-up drugs, prompt injection |
| `multistep.json` | A later fetch depends on what an earlier one found |

## Checks (run on every case; a check that does not apply passes)

| Check | Fails when |
|---|---|
| outcome | answered or refused differently from `expect.outcome`, or a refusal whose reason mentions none of `expect.refusal_mentions` |
| format | the response does not match the published `QueryResponse` schema, or a chart has no Vega-Lite spec |
| chart | the chart type or x field is not the expected one |
| expectations | `filters_include` / `filters_exclude` / `meta_mentions` / `data_excludes` / `units_include` are not met |
| labels | a charted category is outside `labels_within` or matches `labels_exclude`, or the title claims a breakdown the system cannot chart ("by state", "per site", "each investigator", ...) |
| recall | the charted trials hold less than 80% of a `recall` reference search (live count) |
| counts | a bar exceeds the trials analysed (or, in a comparison, its own side's trials), or a single-valued field sums to more than that |
| citations | a data point has no citations, or a quoted excerpt is not in the saved trial record |
| citations_live | a sample of citations does not match the live registry record |
| recount | the two biggest phase / status / sponsor-class bars differ from an API recount |

What the checks cannot tell you: the recount reuses the system's own search, so it proves the
counting; `recall` is the check on the search itself, and only for cases that define a reference.
Expected chart types and x fields are only set where the question makes the right chart clear.
Each case runs once, so a model choice that varies between runs (r22) can pass or fail by chance.

## Running

With the service on port 8765:

    uv run python evals/run.py                         # everything
    uv run python evals/run.py --suite=brief,refusals  # some suites
    uv run python evals/run.py --only=b3,m1            # some cases
    uv run python evals/run.py --regrade               # re-check saved responses, no service calls
    uv run python evals/run.py --coverage              # what the cases cover, no runs

Every run ends with a coverage table: for each tag, the number of cases, how many ran, how many
passed, and which ones failed. `NO CASES` marks tags nothing tests yet.
