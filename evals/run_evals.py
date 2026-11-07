"""Ask the running service every question in questions.json, then check each answer independently.

    uv run python evals/run_evals.py [questions.json] [report.json] [--only id1,id2]

Needs the service on localhost:8765. For each answer it checks:
  - answered or refused as expected
  - the counts are consistent with the trials analysed
  - every citation's excerpt really is in the saved trial record
  - for phase / status / sponsor-class bars, the top two bars recounted straight from the
    ClinicalTrials.gov API with the same search (and the same series side, if any)
"""

import json
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SERVICE = "http://localhost:8765"
CTGOV = "https://clinicaltrials.gov/api/v2/studies"
ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent

AREA = {
    "phase": "Phase",
    "overall_status": "OverallStatus",
    "sponsor_class": "LeadSponsorClass",
}
SINGLE_VALUED = {
    "overall_status",
    "lead_sponsor",
    "sponsor_class",
    "start_year",
    "completion_year",
    "group",
}
# citation field path suffix -> (visualization field, key on the saved trial)
CITED = {
    "designModule.phases": ("phase", "phases"),
    "overallStatus": ("overall_status", "overall_status"),
    "leadSponsor.name": ("lead_sponsor", "lead_sponsor"),
    "leadSponsor.class": ("sponsor_class", "sponsor_class"),
    "conditions": ("condition", "conditions"),
    "locations.country": ("country", "countries"),
    "interventions.name": ("intervention", "interventions"),
    "interventions.type": ("intervention_type", "interventions"),
    "enrollmentInfo.count": ("enrollment", "enrollment"),
    "startDateStruct.date": ("start_year", "start_date"),
    "completionDateStruct.date": ("completion_year", "completion_date"),
}


def http_json(url, data=None):
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(
        url, data=body, headers={"content-type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def ask(q):
    body = {k: v for k, v in q.items() if k not in ("id", "expect")}
    started = time.time()
    task = http_json(f"{SERVICE}/queries", body)
    while True:
        status = http_json(f"{SERVICE}/queries/{task['task_id']}")
        if (
            status["status"] in ("succeeded", "failed", "cancelled")
            or time.time() - started > 1800
        ):
            status["seconds"] = round(time.time() - started, 1)
            return q, status
        time.sleep(2)


def ctgov_count(params: dict) -> int:
    query = {**params, "pageSize": 1, "countTotal": "true", "fields": "NCTId"}
    return http_json(f"{CTGOV}?{urllib.parse.urlencode(query)}")["totalCount"]


def trial_values(trial: dict, field: str, key: str) -> set[str]:
    raw = trial.get(key)
    if field == "intervention":
        return {i["name"] for i in raw or []}
    if field == "intervention_type":
        return {i["type"] for i in raw or [] if i.get("type")}
    if field == "enrollment":
        return {str(raw)} if raw is not None else set()
    if isinstance(raw, list):
        return set(raw)
    return {raw} if raw else set()  # dates: the excerpt is the full date


def charted_fetch(folder: Path, meta: dict) -> tuple[Path, list[dict]]:
    """The folder and steps of the fetch the chart was built from."""
    step = next(c for c in meta["chain"] if c["charted"])
    fetch_dir = folder / step["output_dir"]
    return fetch_dir, json.loads((fetch_dir / "steps.json").read_text())


def check_citations(viz, fetch_dir, steps):
    trials = {}
    for s in steps:
        if "trials_file" in s:
            trials.update(
                {
                    t["nct_id"]: t
                    for t in json.loads((fetch_dir / s["trials_file"]).read_text())
                }
            )
    rows = (
        viz["data"]["nodes"] + viz["data"]["edges"]
        if viz["type"] == "network_graph"
        else viz["data"]
    )
    cited = bad = 0
    for row in rows:
        for c in row.get("citations", []):
            cited += 1
            t = trials.get(c["nct_id"])
            match = next(
                (v for path, v in CITED.items() if c["field"].endswith(path)), None
            )
            if (
                t is None
                or match is None
                or c["excerpt"] not in trial_values(t, *match)
            ):
                bad += 1
    return cited, bad


def recount(viz, steps, checks, issues):
    """Recount the top two bars from the API: same search, plus the bar's (and series') value."""
    x = viz["encoding"]["x"]["field"]
    series = (viz["encoding"].get("color") or {}).get("field")
    if series not in (None, "group") and series not in AREA:
        return  # the series value cannot be expressed as an API filter
    by_label = {
        s["label"]: s["params"] for s in steps if s.get("endpoint") == "studies"
    }
    if not by_label:
        return
    for row in sorted(viz["data"], key=lambda r: -r["trial_count"])[:2]:
        label = row["group"] if series == "group" else next(iter(by_label))
        params = dict(by_label[label])
        extra = [f"AREA[{AREA[x]}]{row[x]}"]
        if series in AREA:
            extra.append(f"AREA[{AREA[series]}]{row[series]}")
        if params.get("filter.advanced"):
            extra.insert(0, f"({params['filter.advanced']})")
        params["filter.advanced"] = " AND ".join(extra)
        api = ctgov_count(params)
        side = (
            f"{label}/" if series == "group" else (f"{row[series]}/" if series else "")
        )
        msg = f"recount {side}{row[x]}: chart {row['trial_count']} vs API {api}"
        (checks if api == row["trial_count"] else issues).append(msg)


def verify(q, status):
    checks, issues = [], []
    if q.get("expect") == "refused":
        error = status.get("error") or {}
        ok = status["status"] == "failed" and error.get("error") == "unsupported_query"
        (checks if ok else issues).append(
            f"refused as unanswerable: {error.get('message', '')[:90]}"
        )
        return checks, issues
    if status["status"] != "succeeded":
        issues.append(f"{status['status'].upper()}: {status.get('error')}")
        return checks, issues

    viz, meta = status["result"]["visualization"], status["result"]["meta"]
    fetch_dir, steps = charted_fetch(ROOT / status["output_dir"], meta)
    from_stats = all(s.get("endpoint", "studies") != "studies" for s in steps)

    if viz["type"] != "network_graph":
        x = viz["encoding"]["x"]["field"]
        series = (viz["encoding"].get("color") or {}).get("field")
        counts = [r["trial_count"] for r in viz["data"]]
        if not from_stats:
            if max(counts, default=0) > meta["trials_analyzed"]:
                issues.append("a bar exceeds the trials analysed")
            if (
                x in SINGLE_VALUED
                and series is None
                and sum(counts) > meta["trials_analyzed"]
            ):
                issues.append(
                    f"single-valued {x} sums to {sum(counts)} > {meta['trials_analyzed']} trials"
                )
        checks.append(
            f"counts consistent ({len(counts)} rows, max {max(counts, default=0)})"
        )

    if from_stats:
        checks.append("registry-wide stats: no citations expected")
    else:
        cited, bad = check_citations(viz, fetch_dir, steps)
        (issues if bad or not cited else checks).append(
            f"citations real: {cited - bad}/{cited}"
        )

    if (
        viz["type"] in ("bar_chart", "grouped_bar_chart", "stacked_bar_chart")
        and viz["encoding"]["x"]["field"] in AREA
    ):
        recount(viz, steps, checks, issues)
    return checks, issues


def summary(q, status, checks, issues):
    result = status.get("result") or {}
    viz, meta = result.get("visualization") or {}, result.get("meta") or {}
    enc = viz.get("encoding") or {}
    return {
        "id": q["id"], "query": q["query"], "expect": q.get("expect"), "status": status["status"],
        "seconds": status["seconds"], "chart": viz.get("type"), "title": viz.get("title"),
        "x": (enc.get("x") or {}).get("field"), "series": (enc.get("color") or {}).get("field"),
        "trials": meta.get("trials_analyzed"), "fetches": len(meta.get("chain") or []),
        "warnings": meta.get("warnings"), "checks": checks, "issues": issues,
        "output_dir": status.get("output_dir"),
    }  # fmt: skip


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--only")]
    only = next(
        (
            a.split("=", 1)[1].split(",")
            for a in sys.argv[1:]
            if a.startswith("--only=")
        ),
        None,
    )
    questions_path = Path(args[0]) if args else HERE / "questions.json"
    report_path = Path(args[1]) if len(args) > 1 else HERE / "report.json"
    questions = [
        q for q in json.loads(questions_path.read_text()) if not only or q["id"] in only
    ]

    with ThreadPoolExecutor(3) as pool:  # three questions at a time
        answered = list(pool.map(ask, questions))
    report = []
    for q, status in answered:
        checks, issues = verify(q, status)
        report.append(summary(q, status, checks, issues))
        chart = str(report[-1]["chart"])
        print(f"[{q['id']:4}] {status['status']:9} {status['seconds']:6}s {chart:18} "
              f"{'ISSUES: ' + '; '.join(issues) if issues else 'ok'}", flush=True)  # fmt: skip
    report_path.write_text(json.dumps(report, indent=1))
    failed = sum(bool(r["issues"]) for r in report)
    print(f"\n{len(report) - failed}/{len(report)} passed; report in {report_path}")


if __name__ == "__main__":
    main()
