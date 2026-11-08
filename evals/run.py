"""Run eval cases against the live service, check every answer, and report coverage by tag.

    uv run python evals/run.py                      # every suite
    uv run python evals/run.py --suite=brief,refusals
    uv run python evals/run.py --only=b3,m1
    uv run python evals/run.py --regrade            # re-check saved responses, no service calls
    uv run python evals/run.py --coverage           # just the coverage table of the cases, no runs

Needs the service on localhost:8765 (except --regrade and --coverage). Raw responses go to
evals/results/responses/<id>.json, the report to evals/results/report.json.
"""

import json
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from checks import CHECKS, TAGS, check_case_definition, http_json

SERVICE = "http://localhost:8765"
HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
TIMEOUT_S = 1800
WORKERS = 3


def load_cases(suites: list[str] | None, only: list[str] | None) -> list[dict]:
    cases = []
    for path in sorted((HERE / "cases").glob("*.json")):
        if suites and path.stem not in suites:
            continue
        for case in json.loads(path.read_text()):
            if not only or case["id"] in only:
                cases.append(case | {"suite": path.stem})
    problems = {c["id"]: p for c in cases if (p := check_case_definition(c))}
    if problems:
        sys.exit(f"Bad case definitions: {problems}")
    return cases


def ask(case: dict) -> dict:
    started = time.time()
    task = http_json(f"{SERVICE}/queries", case["request"])
    while True:
        status = http_json(f"{SERVICE}/queries/{task['task_id']}")
        if status["status"] in ("succeeded", "failed") or time.time() - started > TIMEOUT_S:
            return status | {"seconds": round(time.time() - started, 1)}
        time.sleep(2)


def grade(case: dict, status: dict) -> dict:
    issues = []
    for check in CHECKS:
        try:
            issues += [f"{check.__name__.removeprefix('check_')}: {p}" for p in check(case, status)]
        except Exception as exc:  # a broken check is reported, not hidden
            issues.append(f"{check.__name__.removeprefix('check_')}: check crashed: {exc!r}")
    viz = (status.get("result") or {}).get("visualization") or {}
    return {
        "id": case["id"], "suite": case["suite"], "intent": case["intent"], "tags": case["tags"],
        "query": case["request"]["query"], "expect": case["expect"]["outcome"], "status": status.get("status"),
        "passed": not issues, "issues": issues, "chart": viz.get("type"), "title": viz.get("title"),
        "seconds": status.get("seconds"), "output_dir": status.get("output_dir"), "note": case.get("note"),
    }  # fmt: skip


def coverage(cases: list[dict], results: list[dict] | None = None) -> str:
    """Per tag: how many cases, and (after a run) how many passed. Tags with no case are untested."""
    by_tag = defaultdict(list)
    for c in cases:
        for t in c["tags"]:
            by_tag[t].append(c["id"])
    passed = {r["id"]: r["passed"] for r in results or []}
    lines = [f"{'tag':28} {'cases':>5} {'run':>4} {'pass':>5}  failing / description"]
    for tag, description in TAGS.items():
        ids = by_tag.get(tag, [])
        if not ids:
            lines.append(f"{tag:28} {0:>5} {'-':>4} {'-':>5}  NO CASES: {description}")
            continue
        run = [i for i in ids if i in passed]
        if results is None or not run:
            lines.append(f"{tag:28} {len(ids):>5} {'-' if results is None else 0:>4} {'-':>5}  {description}")
            continue
        failing = [i for i in run if not passed[i]]
        detail = ("failing: " + " ".join(failing)) if failing else description
        lines.append(f"{tag:28} {len(ids):>5} {len(run):>4} {len(run) - len(failing):>5}  {detail}")
    return "\n".join(lines)


def main():
    args = dict(a.lstrip("-").split("=", 1) if "=" in a else (a.lstrip("-"), True) for a in sys.argv[1:])
    split = lambda key: args[key].split(",") if isinstance(args.get(key), str) else None
    cases = load_cases(split("suite"), split("only"))
    if args.get("coverage"):
        print(coverage(cases))
        return

    responses = RESULTS / "responses"
    responses.mkdir(parents=True, exist_ok=True)

    def one(case):
        saved = responses / f"{case['id']}.json"
        if args.get("regrade"):
            if not saved.exists():
                return None
            status = json.loads(saved.read_text())
        else:
            status = ask(case)
            saved.write_text(json.dumps(status, indent=1))
        result = grade(case, status)
        mark = "PASS" if result["passed"] else "FAIL"
        print(f"{mark} {case['id']:5} {result['status'] or '-':9} {result['chart']!s:18} {case['intent'][:60]}"
              + "".join(f"\n       - {i}" for i in result["issues"]), flush=True)  # fmt: skip
        return result

    with ThreadPoolExecutor(WORKERS) as pool:
        results = [r for r in pool.map(one, cases) if r]
    (RESULTS / "report.json").write_text(json.dumps(results, indent=1))
    print(f"\n{sum(r['passed'] for r in results)}/{len(results)} passed\n\n{coverage(cases, results)}")


if __name__ == "__main__":
    main()
