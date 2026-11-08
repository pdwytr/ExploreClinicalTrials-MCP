"""Black-box eval: realistic questions against the running service (port 8765).

    python3 evals/realistic/run.py [--only=r01,r05] [--workers=4] [regrade]

`regrade` re-scores the saved outputs in out/ without calling the service.

Uses only the public HTTP API of the service plus the public ClinicalTrials.gov API to
verify citations. Writes raw results to evals/realistic/out/<id>.json and a summary to
evals/realistic/report.json.
"""

import json
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = "http://localhost:8765"
CTG = "https://clinicaltrials.gov/api/v2/studies/"
HERE = Path(__file__).parent
OUT = HERE / "out"
TIMEOUT_S = 600


def http(url, body=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body else None,
                                 headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def ask(q):
    body = {k: v for k, v in q.items() if k not in ("id", "who", "expect", "want_type", "note")}
    code, task = http(f"{BASE}/queries", body)
    if code != 202:
        return {"status": f"http_{code}", "error": task}
    t0 = time.time()
    while time.time() - t0 < TIMEOUT_S:
        time.sleep(3)
        _, task = http(f"{BASE}/queries/{task['task_id']}")
        if task["status"] not in ("queued", "running"):
            task["_seconds"] = round(time.time() - t0, 1)
            return task
    return {"status": "timeout"}


def get_path(obj, dotted):
    vals = [obj]
    for part in dotted.split("."):
        nxt = []
        for v in vals:
            if isinstance(v, dict) and part in v:
                nxt.append(v[part])
            elif isinstance(v, list):
                nxt += [x[part] for x in v if isinstance(x, dict) and part in x]
        vals = nxt
    return vals


_study_cache = {}


def verify_citation(c):
    """Does the excerpt really appear in that trial's record (live API)?"""
    nct = c.get("nct_id")
    if nct not in _study_cache:
        try:
            with urllib.request.urlopen(CTG + nct, timeout=30) as r:
                _study_cache[nct] = json.loads(r.read())
        except Exception as e:
            _study_cache[nct] = {"_error": str(e)}
    study = _study_cache[nct]
    if "_error" in study:
        return False, f"{nct}: not found in registry ({study['_error']})"
    hay = json.dumps(get_path(study, c["field"])) if c.get("field") else json.dumps(study)
    ok = str(c.get("excerpt", "")).lower() in hay.lower()
    return ok, None if ok else f"{nct}: excerpt {c.get('excerpt')!r} not in {c.get('field')}"


def datums(viz):
    if viz.get("type") == "network_graph":
        d = viz.get("data") or {}
        return (d.get("nodes") or []) + (d.get("edges") or [])
    return viz.get("data") or []


def grade(q, task):
    res = task.get("result") or {}
    viz = res.get("visualization") or {}
    meta = res.get("meta") or {}
    rows = datums(viz)
    answered = task.get("status") == "succeeded" and bool(rows)
    issues = []

    if q["expect"] == "answered" and not answered:
        issues.append(f"expected an answer, got status={task.get('status')} error={str(task.get('error'))[:200]}")
    if q["expect"] == "refused" and answered:
        issues.append(f"expected a refusal, got a {viz.get('type')} with {len(rows)} datums: {viz.get('title')!r}")

    if answered:
        family = {"grouped_bar_chart": "bar_chart"}
        if q.get("want_type") and family.get(viz.get("type"), viz.get("type")) != q["want_type"]:
            issues.append(f"chart type {viz.get('type')} (expected {q['want_type']})")
        uncited = [r for r in rows if not r.get("citations") and r.get("trial_count", 1) != 0]
        if uncited:
            issues.append(f"{len(uncited)}/{len(rows)} datums have no citations")
        sample = [c for r in rows[:3] for c in (r.get("citations") or [])[:2]]
        bad = [msg for ok, msg in map(verify_citation, sample) if not ok]
        if bad:
            issues.append(f"{len(bad)}/{len(sample)} sampled citations fail live check: " + "; ".join(bad[:3]))
        if not meta.get("total_trials_matched"):
            issues.append("meta.total_trials_matched missing/zero")
        if q["id"] == "r22" and "melanoma" not in json.dumps(meta).lower():
            issues.append("structured condition=melanoma was not applied (meta never mentions melanoma)")
        if q["id"] == "r22" and "lung" in json.dumps(meta.get("filters_applied")).lower():
            issues.append("question text 'lung cancer' leaked into filters despite structured condition")
        if q["id"] == "r29" and "1000" in json.dumps([r for r in rows if not isinstance(r, str)]):
            issues.append("the injected count 1000 appears in the data")

    return {
        "id": q["id"], "who": q["who"], "query": q["query"], "expect": q["expect"],
        "status": task.get("status"), "pass": not issues, "issues": issues,
        "type": viz.get("type"), "title": viz.get("title"), "datums": len(rows),
        "trials_matched": meta.get("total_trials_matched"), "interpretation": meta.get("interpretation"),
        "warnings": meta.get("warnings"), "seconds": task.get("_seconds"),
        "error": task.get("error"),
    }


def main():
    args = dict(a.lstrip("-").split("=", 1) for a in sys.argv[1:] if "=" in a)
    qs = json.loads((HERE / "questions.json").read_text())
    if "only" in args:
        qs = [q for q in qs if q["id"] in args["only"].split(",")]
    OUT.mkdir(exist_ok=True)

    def one(q):
        saved = OUT / f"{q['id']}.json"
        task = json.loads(saved.read_text()) if "regrade" in sys.argv and saved.exists() else ask(q)
        (OUT / f"{q['id']}.json").write_text(json.dumps(task, indent=1))
        g = grade(q, task)
        print(f"{'PASS' if g['pass'] else 'FAIL'} {q['id']} [{g['status']}] {g['type'] or '-'} "
              f"{g['title'] or ''!r}" + "".join(f"\n      - {i}" for i in g["issues"]), flush=True)
        return g

    with ThreadPoolExecutor(int(args.get("workers", 4))) as ex:
        results = list(ex.map(one, qs))
    (HERE / "report.json").write_text(json.dumps(results, indent=1))
    print(f"\n{sum(r['pass'] for r in results)}/{len(results)} passed")


if __name__ == "__main__":
    main()
