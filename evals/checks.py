"""What an eval case may be tagged with, and every check run on a response.

A case says what it sends and what it expects (see cases/*.json and README.md); each check
below looks at the service's answer and returns the problems it found (empty list = fine).
Checks that do not apply to a case return nothing.
"""

import json
import re
import time
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
    "chart.scatter": "Two numeric fields per trial (enrollment against duration)",
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
    # known limitations: the honest answer is a refusal that names the missing field
    "gap.field_not_fetched": "Needs a field the system does not fetch (investigators, sites, US state): must refuse and say why",
}

RECOUNT_FIELDS = {"phase": "Phase", "overall_status": "OverallStatus", "sponsor_class": "LeadSponsorClass"}
SINGLE_VALUED = {"overall_status", "lead_sponsor", "sponsor_class", "start_year", "completion_year", "group"}
LIVE_CITATION_SAMPLE = 6  # citations checked against the live registry per case
RECALL_MIN = 0.8  # share of a reference search's trials the charted fetch must contain
RECALL_MAX_PAGES = 20  # reference searches are fetched as NCT IDs, 1000 per page

# Every key a case may put in "expect"; anything else is a typo and stops the run.
EXPECT_KEYS = {
    "outcome", "chart", "x", "meta_mentions", "filters_include", "filters_exclude", "data_excludes",
    "refusal_mentions", "recall", "labels_within", "labels_exclude", "units_include",
}  # fmt: skip

# Named label sets for expect.labels_within, spelled as the registry spells countries.
REGIONS = {
    "$EUROPE": {
        "albania", "andorra", "austria", "belarus", "belgium", "bosnia and herzegovina", "bulgaria", "croatia",
        "cyprus", "czechia", "czech republic", "denmark", "estonia", "finland", "france", "georgia", "germany",
        "greece", "hungary", "iceland", "ireland", "italy", "kosovo", "latvia", "liechtenstein", "lithuania",
        "luxembourg", "malta", "moldova", "moldova, republic of", "monaco", "montenegro", "netherlands",
        "north macedonia", "norway", "poland", "portugal", "romania", "russia", "russian federation",
        "san marino", "serbia", "slovakia", "slovenia", "spain", "sweden", "switzerland", "turkey",
        "turkey (türkiye)", "türkiye", "ukraine", "united kingdom",
    },
}  # fmt: skip

# A title claiming a breakdown by a dimension the system cannot chart ("...in the US by state" over a
# country chart). Only "by / per / each / across <dimension>" counts: "trials with sites in India"
# names a filter, not a breakdown.
MISSING_DIMENSIONS = re.compile(
    r"\b(?:by|per|each|across)\s+(?:us\s+|u\.s\.\s+)?"
    r"(states?|cit(?:y|ies)|sites?|facilit(?:y|ies)|investigators?|duration)\b"
)


def check_case_definition(case: dict) -> list[str]:
    """The case itself is well formed (run before sending anything)."""
    problems = [f"unknown tag {t!r}" for t in case.get("tags", []) if t not in TAGS]
    if case.get("expect", {}).get("outcome") not in ("answered", "refused", "either"):
        problems.append("expect.outcome must be answered, refused or either")
    if not case.get("intent"):
        problems.append("missing intent")
    expect = case.get("expect", {})
    problems += [f"unknown expect key {k!r}" for k in expect if k not in EXPECT_KEYS]
    if expect.get("refusal_mentions") and expect["outcome"] != "refused":
        problems.append("refusal_mentions needs expect.outcome = refused")
    for ref in expect.get("recall") or []:
        if not isinstance(ref, dict) or not isinstance(ref.get("search"), dict) or not ref["search"]:
            problems.append("each expect.recall entry needs a non-empty 'search' of API parameters")
    for name in ("labels_within", "labels_exclude"):
        unknown = [v for v in expect.get(name) or [] if v.startswith("$") and v not in REGIONS]
        problems += [f"unknown label set {v!r} in {name}" for v in unknown]
    return problems


# --- helpers ---------------------------------------------------------------------------------


def http_json(url: str, body: dict | None = None, attempts: int = 6) -> dict:
    """GET (or POST with a body) JSON. ClinicalTrials.gov rate-limits bursts (429): back off and retry,
    so a busy regrade reports the answer's problems, not the registry's throttling."""
    data = json.dumps(body).encode() if body else None
    for attempt in range(attempts):
        req = urllib.request.Request(url, data=data, headers={"content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 503) or attempt == attempts - 1:
                raise
            time.sleep(float(exc.headers.get("Retry-After") or 2**attempt))
    raise AssertionError("unreachable")


def rows(viz: dict) -> list[dict]:
    if viz.get("type") == "network_graph":
        return (viz.get("data") or {}).get("nodes", []) + (viz.get("data") or {}).get("edges", [])
    return viz.get("data") or []


def answered(status: dict) -> bool:
    return status.get("status") == "succeeded" and bool(rows((status.get("result") or {}).get("visualization") or {}))


def as_list(value) -> list:
    return value if isinstance(value, list) else [value]


def chart_labels(viz: dict, only_field: str | None = None) -> list[str]:
    """The categories a reader sees: x values (and a non-group series) for charts, node labels for
    networks. `only_field` keeps one field's labels (network nodes by their group)."""
    if viz.get("type") == "network_graph":
        nodes = (viz.get("data") or {}).get("nodes", [])
        return [str(n.get("label")) for n in nodes if not only_field or n.get("group") == only_field]
    enc = viz.get("encoding") or {}
    fields = [enc.get("x", {}).get("field"), (enc.get("color") or {}).get("field")]
    fields = [f for f in fields if f and f != "group" and (not only_field or f == only_field)]
    return sorted({str(r[f]) for r in viz.get("data") or [] for f in fields if r.get(f) is not None})


def charted_trials(status: dict) -> dict[str, set[str]]:
    """NCT IDs per step label of the fetch the chart was built from (from the saved trial files)."""
    fetched = charted_fetch(status)
    if not fetched:
        return {}
    folder, steps = fetched
    return {
        s["label"]: {t["nct_id"] for t in json.loads((folder / s["trials_file"]).read_text())}
        for s in steps
        if s.get("trials_file")
    }


_reference_cache: dict[str, set[str]] = {}


def reference_ids(search: dict) -> set[str]:
    """Every NCT ID a reference search matches today (live), so the expectation never goes stale."""
    key = json.dumps(search, sort_keys=True)
    if key not in _reference_cache:
        ids: set[str] = set()
        token = None
        for _ in range(RECALL_MAX_PAGES):
            params = {**search, "fields": "NCTId", "pageSize": 1000} | ({"pageToken": token} if token else {})
            page = http_json(f"{CTGOV}?{urllib.parse.urlencode(params)}")
            ids |= {s["protocolSection"]["identificationModule"]["nctId"] for s in page.get("studies", [])}
            token = page.get("nextPageToken")
            if not token:
                break
        _reference_cache[key] = ids
    return _reference_cache[key]


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
    reasons = case["expect"].get("refusal_mentions")
    message = str((status.get("error") or {}).get("message", "")).lower()
    if want == "refused" and reasons and not any(r.lower() in message for r in reasons):
        return [f"refused, but the reason mentions none of {reasons}: {message[:150]}"]
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
    """Case-specific text expectations. filters_include / filters_exclude look only at the searches that
    actually ran (meta.filters_applied), never at the model's own prose; meta_mentions looks at all of meta."""
    if not answered(status):
        return []
    expect, meta, problems = case["expect"], status["result"]["meta"], []
    # unescaped, so an expectation can quote a phrase exactly as the API received it
    filters = json.dumps(meta.get("filters_applied"), ensure_ascii=False).replace('\\"', '"').lower()
    if expect.get("meta_mentions") and expect["meta_mentions"].lower() not in json.dumps(meta).lower():
        problems.append(f"meta never mentions {expect['meta_mentions']!r}")
    for text in as_list(expect.get("filters_include") or []):
        if text.lower() not in filters:
            problems.append(f"the executed searches never use {text!r}")
    for text in as_list(expect.get("filters_exclude") or []):
        if text.lower() in filters:
            problems.append(f"{text!r} leaked into the filters")
    data = rows(status["result"]["visualization"])
    shown = [json.dumps({k: v for k, v in r.items() if k != "citations"}, ensure_ascii=False) for r in data]
    for text in as_list(expect.get("data_excludes") or []):
        if any(text.lower() in row.lower() for row in shown):
            problems.append(f"{text!r} appears in the charted data")
    units = json.dumps(meta.get("units") or {}).lower()
    if expect.get("units_include") and not any(u.lower() in units for u in as_list(expect["units_include"])):
        problems.append(f"meta.units {meta.get('units')} has none of {expect['units_include']}")
    return problems


def check_labels(case, status) -> list[str]:
    """The charted categories stay inside what was asked (labels_within, e.g. "$EUROPE") and avoid what
    must not be shown (labels_exclude, e.g. "Placebo" as a drug), and the title claims no breakdown the
    system cannot chart (state, city, site, investigator, duration)."""
    if not answered(status):
        return []
    viz, expect, problems = status["result"]["visualization"], case["expect"], []
    labels = chart_labels(viz)
    if expect.get("labels_within"):
        allowed = {a.lower() for v in expect["labels_within"] for a in (REGIONS.get(v) or {v})}
        regional = any(v in REGIONS for v in expect["labels_within"])  # a region constrains countries only
        outside = [label for label in (chart_labels(viz, "country") if regional else labels) if label.lower() not in allowed]
        if outside:
            problems.append(f"{len(outside)} charted label(s) outside what was asked: {outside[:6]}")
    for text in expect.get("labels_exclude") or []:
        hits = [label for label in labels if text.lower() in label.lower()]
        if hits:
            problems.append(f"charted label(s) that must not appear: {hits[:4]}")
    claimed = MISSING_DIMENSIONS.search((viz.get("title") or "").lower())
    if claimed:
        problems.append(f"title claims a breakdown by {claimed.group(1)!r}, which the system cannot chart")
    return problems


def check_recall(case, status) -> list[str]:
    """The charted trials contain most of what a hand-written reference search finds (live, today).
    Catches searches that answer a narrower question than asked: brand instead of generic name, an
    alias instead of the registry name, an exact-field filter that drops spellings. Each entry may name
    the compared side(s) it applies to with "match" (substrings of the side label); without it, all
    charted trials are compared."""
    refs = case["expect"].get("recall")
    if not refs or not answered(status):
        return []
    sides = charted_trials(status)
    if not sides:
        return ["recall: no saved trials for the charted fetch"]
    problems = []
    for ref in refs:
        names = [m.lower() for m in ref.get("match") or []]
        chosen = [label for label in sides if not names or any(n in label.lower() for n in names)]
        if not chosen:
            problems.append(f"no charted side matches {ref['match']} (sides: {list(sides)})")
            continue
        got = set().union(*(sides[label] for label in chosen))
        want = reference_ids(ref["search"])
        if not want:
            problems.append(f"reference search {ref['search']} matches nothing: fix the case")
            continue
        share = len(got & want) / len(want)
        if share < ref.get("min", RECALL_MIN):
            problems.append(
                f"{'/'.join(chosen)}: has {len(got & want)} of the {len(want)} trials {ref['search']} finds "
                f"({share:.0%} < {ref.get('min', RECALL_MIN):.0%})"
            )
    return problems


def check_counts(case, status) -> list[str]:
    """No bar exceeds the trials analysed; a single-valued field without series sums to at most that."""
    if not answered(status) or status["result"]["visualization"]["type"] in ("network_graph", "scatter_plot"):
        return []  # networks have sizes and weights; a scatter point is one trial, with no count
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
    # In a comparison, trials_analyzed is the sum of the sides: each bar must fit its own side.
    side_field = "group" if "group" in (x, (viz["encoding"].get("color") or {}).get("field")) else None
    sizes = {label: len(ids) for label, ids in charted_trials(status).items()} if side_field else {}
    over = [r for r in viz["data"] if r.get("group") in sizes and r["trial_count"] > sizes[r["group"]]]
    if over:
        problems.append(f"{len(over)} bar(s) exceed their own side's trials, e.g. {over[0]['group']}: {over[0]['trial_count']}")
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
    """A sample of citations against the live registry record: is the quoted text really there?
    A cited trial the registry does not have (404) is wrong; a registry that cannot be reached
    (throttling, network) says nothing about the answer, so those citations are left unchecked."""
    if not answered(status):
        return []
    sample = [c for r in rows(status["result"]["visualization"])[:3] for c in r.get("citations", [])[:2]]
    sample = sample[:LIVE_CITATION_SAMPLE]
    wrong, unreachable = [], 0
    for c in sample:
        if c["nct_id"] not in _live_cache:
            try:
                _live_cache[c["nct_id"]] = http_json(f"{CTGOV}/{c['nct_id']}")
            except urllib.error.HTTPError as exc:
                _live_cache[c["nct_id"]] = {"_missing" if exc.code == 404 else "_unreachable": str(exc)}
            except (urllib.error.URLError, TimeoutError, ValueError) as exc:  # network
                _live_cache[c["nct_id"]] = {"_unreachable": str(exc)}
        record = _live_cache[c["nct_id"]]
        if "_unreachable" in record:
            unreachable += 1
            continue
        if "_missing" in record:
            wrong.append(f"{c['nct_id']}: not in the registry")
            continue
        value = record
        for part in c["field"].split("."):
            value = [v.get(part) for v in value if isinstance(v, dict)] if isinstance(value, list) else (value or {}).get(part)
        if c["excerpt"].lower() not in json.dumps(value, ensure_ascii=False).lower():
            wrong.append(f"{c['nct_id']}: {c['excerpt']!r} is not in {c['field']}")
    problems = [f"{len(wrong)}/{len(sample) - unreachable} live citations wrong: " + "; ".join(wrong[:2])] if wrong else []
    if sample and unreachable == len(sample):
        problems.append("could not check any citation: the registry was unreachable (rerun to retry)")
    return problems


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
    check_labels,
    check_recall,
    check_counts,
    check_citations,
    check_citations_live,
    check_recount,
]
