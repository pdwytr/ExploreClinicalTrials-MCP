"""What an eval case may be tagged with, and every check run on a response.

A case says what it sends and what it expects (see cases/*.json and README.md); each check
below looks at the service's answer and returns the problems it found (empty list = fine).
Checks that do not apply to a case return nothing.
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from pydantic import ValidationError

from cheiron.models.response import QueryResponse

ROOT = Path(__file__).resolve().parent.parent
CTGOV = "https://clinicaltrials.gov/api/v2/studies"

# The fixed tag list. Every case tag must be one of these; tags with no case show up as
# untested in the coverage table.
TAGS = {
    # where the case comes from
    "source.brief": "One of the example questions in the brief",
    # the chart a correct answer needs
    "chart.bar": "Bar chart of one field",
    "chart.grouped": "Grouped or stacked bars: one field split by another or by compared sides",
    "chart.time_series": "Counts per year",
    "chart.histogram": "Distribution of a numeric field (enrollment)",
    "chart.network": "Network of linked values (sponsor-drug, drug co-occurrence)",
    "chart.scatter": "Two numeric fields per trial",
    # how the question is asked
    "input.structured": "Uses the structured request fields (drug_name, condition, phase, years...)",
    "input.conflict": "Question text and a structured field disagree",
    "input.typo": "Misspellings",
    "input.vague": "Vague or slangy wording",
    "input.brand_name": "A brand name instead of the generic drug name",
    "input.abbreviation": "An abbreviation (NSCLC, COPD)",
    "input.drug_class": "A drug class instead of drugs (GLP-1, chemotherapy)",
    "input.date_range": "A year range or 'since'",
    "input.geography": "Countries or regions",
    "input.status": "Recruitment status (recruiting, completed...)",
    "input.comparison": "Compares drugs, conditions or sponsor kinds",
    "input.top_n": "Asks for the top N",
    "input.share": "Asks for a share or percentage",
    "input.exclusion": "Excludes something ('excluding type 1')",
    "input.numeric_filter": "A numeric condition (enrolled more than 500)",
    "input.follow_up": "Refers to an earlier question ('same thing for Japan')",
    "input.sponsor_alias": "A sponsor known by several names (MSD / Merck Sharp & Dohme)",
    # what the system has to do
    "capability.multistep": "A later fetch depends on what an earlier one found",
    "capability.whole_registry": "About the whole registry (answered from /stats)",
    # data quality the answer must survive
    "data.name_variants": "Charts free-text names that come in several spellings",
    "data.small_sample": "Very few trials match",
    # must not answer
    "refusal.out_of_scope": "Efficacy, safety, dosing, advice or prediction: not in registry records",
    "refusal.missing_context": "Refers to something not given ('this sponsor')",
    "refusal.nonsense": "Gibberish",
    "refusal.made_up_entity": "A drug or condition that does not exist",
    "safety.prompt_injection": "Tries to make the system output given numbers",
    # known limitations: expected to fail until the field exists
    "gap.field_not_fetched": "Needs a field the system does not fetch (investigators, design, US state, duration)",
}

RECOUNT_FIELDS = {"phase": "Phase", "overall_status": "OverallStatus", "sponsor_class": "LeadSponsorClass"}
SINGLE_VALUED = {"overall_status", "lead_sponsor", "sponsor_class", "start_year", "completion_year", "group"}
LIVE_CITATION_SAMPLE = 6  # citations checked against the live registry per case


def check_case_definition(case: dict) -> list[str]:
    """The case itself is well formed (run before sending anything)."""
    problems = [f"unknown tag {t!r}" for t in case.get("tags", []) if t not in TAGS]
    if case.get("expect", {}).get("outcome") not in ("answered", "refused", "either"):
        problems.append("expect.outcome must be answered, refused or either")
    if not case.get("intent"):
        problems.append("missing intent")
    return problems


# --- helpers ---------------------------------------------------------------------------------


def http_json(url: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def rows(viz: dict) -> list[dict]:
    if viz.get("type") == "network_graph":
        return (viz.get("data") or {}).get("nodes", []) + (viz.get("data") or {}).get("edges", [])
    return viz.get("data") or []


def answered(status: dict) -> bool:
    return status.get("status") == "succeeded" and bool(rows((status.get("result") or {}).get("visualization") or {}))


def charted_fetch(status: dict) -> tuple[Path, list[dict]] | None:
    """The saved folder and steps of the fetch the chart was built from."""
    chain = status["result"]["meta"].get("chain") or []
    step = next((c for c in chain if c.get("charted")), None)
    if not step or not status.get("output_dir"):
        return None
    folder = ROOT / status["output_dir"] / step["output_dir"]
    return (folder, json.loads((folder / "steps.json").read_text())) if (folder / "steps.json").exists() else None


# --- checks ----------------------------------------------------------------------------------


def check_outcome(case, status) -> list[str]:
    want = case["expect"]["outcome"]
    if want == "answered" and not answered(status):
        return [f"expected an answer, got {status.get('status')}: {str((status.get('error') or {}).get('message'))[:150]}"]
    if want == "refused" and answered(status):
        return [f"expected a refusal, got a {status['result']['visualization']['type']}"]
    if want == "refused" and (status.get("error") or {}).get("error") not in ("unsupported_query", "no_results"):
        return [f"refused with an unexpected error: {status.get('error')}"]
    return []


def check_format(case, status) -> list[str]:
    """The response matches the published schema (QueryResponse), incl. a Vega-Lite spec for charts."""
    if not answered(status):
        return []
    try:
        response = QueryResponse.model_validate(status["result"])
    except ValidationError as exc:
        return [f"response does not match QueryResponse: {str(exc)[:200]}"]
    problems = []
    if response.visualization.type != "network_graph" and not status["result"].get("vega_lite"):
        problems.append("chart response has no vega_lite spec")
    meta = response.meta
    if not meta.interpretation or not meta.total_trials_matched and meta.trials_analyzed:
        problems.append("meta is missing the interpretation or trial totals")
    return problems


def check_chart(case, status) -> list[str]:
    if not answered(status):
        return []
    viz, expect, problems = status["result"]["visualization"], case["expect"], []
    if expect.get("chart") and viz["type"] not in expect["chart"]:
        problems.append(f"chart {viz['type']}, expected one of {expect['chart']}")
    if expect.get("x") and viz["type"] != "network_graph" and viz["encoding"]["x"]["field"] != expect["x"]:
        problems.append(f"x is {viz['encoding']['x']['field']}, expected {expect['x']}")
    return problems


def check_expectations(case, status) -> list[str]:
    """Case-specific text expectations: meta_mentions, filters_exclude, data_excludes."""
    if not answered(status):
        return []
    expect, meta, problems = case["expect"], status["result"]["meta"], []
    if expect.get("meta_mentions") and expect["meta_mentions"].lower() not in json.dumps(meta).lower():
        problems.append(f"meta never mentions {expect['meta_mentions']!r}")
    if expect.get("filters_exclude") and expect["filters_exclude"].lower() in json.dumps(meta.get("filters_applied")).lower():
        problems.append(f"{expect['filters_exclude']!r} leaked into the filters")
    data = rows(status["result"]["visualization"])
    if expect.get("data_excludes") and any(expect["data_excludes"] in json.dumps(r.get("trial_count", "")) for r in data):
        problems.append(f"{expect['data_excludes']!r} appears as a count in the data")
    return problems


def check_counts(case, status) -> list[str]:
    """No bar exceeds the trials analysed; a single-valued field without series sums to at most that."""
    if not answered(status) or status["result"]["visualization"]["type"] == "network_graph":
        return []
    viz, meta = status["result"]["visualization"], status["result"]["meta"]
    if not meta.get("trials_analyzed"):  # whole-registry stats: counts are not from fetched trials
        return []
    counts = [r["trial_count"] for r in viz["data"]]
    x = viz["encoding"]["x"]["field"]
    problems = []
    if max(counts, default=0) > meta["trials_analyzed"]:
        problems.append("a bar exceeds the trials analysed")
    if x in SINGLE_VALUED and "color" not in viz["encoding"] and sum(counts) > meta["trials_analyzed"]:
        problems.append(f"single-valued {x} sums to {sum(counts)} > {meta['trials_analyzed']} trials")
    return problems


def check_citations(case, status) -> list[str]:
    """Every datum with trials is cited, and the excerpts are in the saved trial records."""
    if not answered(status) or not status["result"]["meta"].get("trials_analyzed"):
        return []
    data = rows(status["result"]["visualization"])
    problems = []
    uncited = [r for r in data if not r.get("citations") and r.get("trial_count", r.get("size", 1))]
    if uncited:
        problems.append(f"{len(uncited)}/{len(data)} data points have no citations")
    fetched = charted_fetch(status)
    if fetched:
        folder, steps = fetched
        saved = {}
        for s in steps:
            if "trials_file" in s:
                saved.update({t["nct_id"]: json.dumps(t, ensure_ascii=False) for t in json.loads((folder / s["trials_file"]).read_text())})
        cited = [c for r in data for c in r.get("citations", [])]
        missing = [c["nct_id"] for c in cited if c["nct_id"] not in saved or c["excerpt"] not in saved[c["nct_id"]]]
        if missing:
            problems.append(f"{len(missing)}/{len(cited)} citations not found in the saved records, e.g. {missing[:3]}")
    return problems


_live_cache: dict[str, dict] = {}


def check_citations_live(case, status) -> list[str]:
    """A sample of citations against the live registry record: is the quoted text really there?"""
    if not answered(status):
        return []
    sample = [c for r in rows(status["result"]["visualization"])[:3] for c in r.get("citations", [])[:2]]
    problems = []
    for c in sample[:LIVE_CITATION_SAMPLE]:
        if c["nct_id"] not in _live_cache:
            try:
                _live_cache[c["nct_id"]] = http_json(f"{CTGOV}/{c['nct_id']}")
            except (urllib.error.URLError, TimeoutError, ValueError) as exc:  # missing trial, network
                _live_cache[c["nct_id"]] = {"_error": str(exc)}
        record = _live_cache[c["nct_id"]]
        value = record
        for part in c["field"].split("."):
            value = [v.get(part) for v in value if isinstance(v, dict)] if isinstance(value, list) else (value or {}).get(part)
        if c["excerpt"].lower() not in json.dumps(value, ensure_ascii=False).lower():
            problems.append(f"{c['nct_id']}: {c['excerpt']!r} is not in {c['field']}")
    return [f"{len(problems)}/{min(len(sample), LIVE_CITATION_SAMPLE)} live citations wrong: " + "; ".join(problems[:2])] if problems else []


def check_recount(case, status) -> list[str]:
    """The two biggest phase / status / sponsor-class bars, recounted from the API with the same search."""
    if not answered(status):
        return []
    viz = status["result"]["visualization"]
    if viz["type"] not in ("bar_chart", "grouped_bar_chart", "stacked_bar_chart"):
        return []
    x, series = viz["encoding"]["x"]["field"], (viz["encoding"].get("color") or {}).get("field")
    fetched = charted_fetch(status)
    if x not in RECOUNT_FIELDS or (series not in (None, "group") and series not in RECOUNT_FIELDS) or not fetched:
        return []
    by_label = {s["label"]: s["params"] for s in fetched[1] if s.get("endpoint") == "studies"}
    if not by_label:
        return []
    problems = []
    for row in sorted(viz["data"], key=lambda r: -r["trial_count"])[:2]:
        params = dict(by_label[row["group"]] if series == "group" else next(iter(by_label.values())))
        extra = [f"AREA[{RECOUNT_FIELDS[x]}]{row[x]}"]
        if series in RECOUNT_FIELDS:
            extra.append(f"AREA[{RECOUNT_FIELDS[series]}]{row[series]}")
        if params.get("filter.advanced"):
            extra.insert(0, f"({params['filter.advanced']})")
        params |= {"filter.advanced": " AND ".join(extra), "pageSize": 1, "countTotal": "true", "fields": "NCTId"}
        api = http_json(f"{CTGOV}?{urllib.parse.urlencode(params)}")["totalCount"]
        if api != row["trial_count"]:
            problems.append(f"{row[x]}: chart {row['trial_count']} vs API {api}")
    return problems


CHECKS = [
    check_outcome,
    check_format,
    check_chart,
    check_expectations,
    check_counts,
    check_citations,
    check_citations_live,
    check_recount,
]
