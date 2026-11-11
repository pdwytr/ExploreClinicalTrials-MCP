"""The chart page's CSV downloads (the <csv> block of web/index.html), run in Node on the saved
examples. Skipped where Node is not installed."""

import csv
import io
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "src" / "studytrials" / "web" / "index.html"
EXAMPLES = ROOT / "examples"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs Node")


def run(function: str, viz: dict) -> list[dict]:
    html = PAGE.read_text()
    code = html[html.index("// <csv>") : html.index("// </csv>")]
    script = code + f"\nprocess.stdout.write({function}(JSON.parse(require('fs').readFileSync(0, 'utf8'))));"
    out = subprocess.run(["node", "-e", script], input=json.dumps(viz), capture_output=True, text=True, check=True)
    return list(csv.DictReader(io.StringIO(out.stdout)))


def viz(example: str) -> dict:
    return json.loads((EXAMPLES / example / "response.json").read_text())["visualization"]


def test_chart_data_has_one_row_per_value_and_no_sources():
    comparison = viz("2-comparison")
    rows = run("chartDataCsv", comparison)
    assert len(rows) == len(comparison["data"])
    assert set(rows[0]) == {"phase", "group", "trial_count"}
    assert rows[0] == {k: str(v) for k, v in comparison["data"][0].items() if k not in ("citations", "nct_ids")}


def test_trial_list_holds_every_trial_behind_the_chart_once():
    comparison = viz("2-comparison")
    rows = run("trialListCsv", comparison)
    expected = {n for row in comparison["data"] for n in row["nct_ids"]}
    assert [r["nct_id"] for r in rows] == sorted(expected)
    first = comparison["data"][0]
    trial = next(r for r in rows if r["nct_id"] == first["citations"][0]["nct_id"])
    assert trial["title"] == first["citations"][0]["title"]
    assert trial["url"] == f"https://clinicaltrials.gov/study/{trial['nct_id']}"
    assert f"phase={first['phase']}; group={first['group']}" in trial["counted_in"]


def test_a_network_lists_nodes_links_and_their_trials():
    network = viz("4-network")
    rows = run("chartDataCsv", network)
    assert sum(r["kind"] == "node" for r in rows) == len(network["data"]["nodes"])
    assert sum(r["kind"] == "link" for r in rows) == len(network["data"]["edges"])
    trials = run("trialListCsv", network)
    expected = {n for part in ("nodes", "edges") for item in network["data"][part] for n in item.get("nct_ids") or []}
    assert {r["nct_id"] for r in trials} == expected


def test_spreadsheet_formulas_and_separators_are_escaped():
    hostile = {"type": "bar_chart", "data": [{"sponsor": '=HYPERLINK("x"), "Inc"', "trial_count": 2, "nct_ids": [], "citations": []}]}
    (row,) = run("chartDataCsv", hostile)
    assert row["sponsor"] == "'" + '=HYPERLINK("x"), "Inc"'  # quoted, and not a formula
    assert row["trial_count"] == "2"
