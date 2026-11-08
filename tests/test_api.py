"""The HTTP service end to end, with a fake agent and fake API source; outputs go to a temp folder."""

import json
import time

from fastapi.testclient import TestClient

from cheiron.api.app import create_app
from cheiron.api.outputs import QueryOutputs
from cheiron.api.tasks import TaskStore
from cheiron.fetch.models import DataVersion, Trial
from cheiron.fetch.stats import FieldValuesResponse
from cheiron.workflow import AgentResult, ChartPlan, Dimension, FetchResult, SearchPlan, StatsResult
from cheiron.workflow.errors import UnsupportedQuery
from cheiron.workflow.pipeline import QueryWorkflow, check_chart_plan
from cheiron.workflow.profile import build_profile

DATA_TS = "2026-11-06T10:00:05"

COMPARISON = SearchPlan(
    steps=[{"endpoint": "studies", "label": "Nivolumab", "drugs": ["nivolumab"]},
           {"endpoint": "studies", "label": "Pembrolizumab", "drugs": ["pembrolizumab"]}],
    rationale="Each drug's trials.",
)  # fmt: skip
PHASE_BY_DRUG = ChartPlan(
    intent="magnitude", chart_type="grouped_bar_chart", title="Phases by drug", x=Dimension.PHASE, series=Dimension.GROUP
)


class Agent:
    """Behaves like QueryAgent: fetch the plan through code, profile it, check the chart."""

    def __init__(self, plan=COMPARISON, chart=PHASE_BY_DRUG, fail: Exception | None = None):
        self.plan, self.chart, self.fail = plan, chart, fail

    async def decide(self, request, fetch, log):
        if self.fail:
            raise self.fail
        outcome = await fetch(self.plan)
        profile = build_profile(outcome.trials_by_group, outcome.total_matched)
        return AgentResult(self.chart, outcome, profile, check_chart_plan(self.chart, outcome.plan, profile), [], [])


class Source:
    async def data_version(self):
        return DataVersion(api_version="2.0.5", data_timestamp=DATA_TS)

    async def search(self, params, limit=None, on_progress=None):
        n = 2 if "nivolumab" in params.search.get("query.intr", "") else 3
        trials = [Trial(nct_id=f"NCT{i:08d}", phases=["PHASE3"]) for i in range(n)]
        if on_progress:
            on_progress(n, n)
        return FetchResult(trials=trials, total_matched=n)

    async def fetch_stats(self, step):
        data = FieldValuesResponse.model_validate(
            [{"field": "protocolSection.designModule.phases", "piece": "Phase", "type": "ENUM", "missingStudiesCount": 0,
              "uniqueValuesCount": 2, "topValues": [{"value": "PHASE2", "studiesCount": 5}, {"value": "PHASE3", "studiesCount": 3}]}]
        )  # fmt: skip
        return StatsResult(endpoint=step.endpoint, data=data)


def make_client(tmp_path, agent):
    async def factory(stack):
        return TaskStore(QueryWorkflow(agent=agent, source=Source()), QueryOutputs(tmp_path))

    return TestClient(create_app(factory))


def wait_until_finished(client, task_id, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/queries/{task_id}").json()
        if body["status"] in ("succeeded", "failed"):
            return body
        time.sleep(0.02)
    raise AssertionError("task did not finish")


QUESTION = {"query": "Compare phases for nivolumab vs pembrolizumab", "trial_phase": ["PHASE3"]}


def test_submit_poll_and_get_the_visualization(tmp_path):
    with make_client(tmp_path, Agent()) as client:
        submitted = client.post("/queries", json=QUESTION)
        assert submitted.status_code == 202 and submitted.json()["result"] is None
        task_id = submitted.json()["task_id"]
        assert submitted.headers["location"] == f"/queries/{task_id}"
        done = wait_until_finished(client, task_id)

    assert done["status"] == "succeeded" and done["progress"]["trials_fetched"] == 5
    result = done["result"]
    assert result["visualization"]["type"] == "grouped_bar_chart"
    rows = {(r["phase"], r["group"]): r["trial_count"] for r in result["visualization"]["data"]}
    assert rows == {("PHASE3", "Nivolumab"): 2, ("PHASE3", "Pembrolizumab"): 3}
    assert result["visualization"]["data"][0]["citations"][0]["nct_id"] == "NCT00000000"
    assert result["meta"]["data_as_of"] == DATA_TS and result["meta"]["total_trials_matched"] == 5
    assert result["vega_lite"]["encoding"]["xOffset"]["field"] == "group"


def test_outputs_on_disk_include_the_response(tmp_path):
    with make_client(tmp_path, Agent()) as client:
        task_id = client.post("/queries", json=QUESTION).json()["task_id"]
        done = wait_until_finished(client, task_id)

    folder = tmp_path / task_id  # one folder per query, named by its UUID
    names = sorted(p.name for p in folder.iterdir())
    assert names == ["fetch-1", "meta.json", "request.json", "response.json", "trace.json"]
    fetch = folder / "fetch-1"
    assert sorted(p.name for p in fetch.iterdir()) == ["plan.json", "profile.json", "steps.json", "trials"]
    assert json.loads((folder / "request.json").read_text()) == QUESTION
    assert json.loads((folder / "response.json").read_text()) == done["result"]  # same as returned
    steps = json.loads((fetch / "steps.json").read_text())
    assert [s["trials_file"] for s in steps] == ["trials/1-nivolumab.json", "trials/2-pembrolizumab.json"]
    assert steps[0]["params"]["filter.advanced"] == "AREA[Phase](PHASE3)"  # user filter recorded as executed
    meta = json.loads((folder / "meta.json").read_text())
    assert meta["status"] == "succeeded" and meta["trials_fetched"] == 5


def test_every_query_gets_its_own_folder(tmp_path):
    with make_client(tmp_path, Agent()) as client:
        ids = [client.post("/queries", json=QUESTION).json()["task_id"] for _ in range(2)]
        for task_id in ids:
            wait_until_finished(client, task_id)
    assert ids[0] != ids[1]
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(ids)


def test_unanswerable_question_fails_with_the_reason_and_keeps_request_on_disk(tmp_path):
    with make_client(tmp_path, Agent(fail=UnsupportedQuery("Efficacy is not in registry records."))) as client:
        task_id = client.post("/queries", json=QUESTION).json()["task_id"]
        done = wait_until_finished(client, task_id)

    assert done["status"] == "failed" and done["result"] is None
    assert done["error"] == {"error": "unsupported_query", "message": "Efficacy is not in registry records.", "details": {}}
    folder = tmp_path / task_id
    assert sorted(p.name for p in folder.iterdir()) == ["meta.json", "request.json"]
    assert json.loads((folder / "meta.json").read_text())["error"]["error"] == "unsupported_query"


def test_unexpected_error_is_hidden_behind_a_generic_message(tmp_path):
    with make_client(tmp_path, Agent(fail=RuntimeError("secret internals"))) as client:
        done = wait_until_finished(client, client.post("/queries", json=QUESTION).json()["task_id"])
    assert done["error"]["error"] == "internal_error" and "secret" not in done["error"]["message"]


def test_invalid_request_is_rejected_before_any_task(tmp_path):
    with make_client(tmp_path, Agent()) as client:
        response = client.post("/queries", json={"query": "x", "drugname": "typo"})
    assert response.status_code == 422
    assert not any(tmp_path.iterdir())


def test_unknown_task_is_404_and_health_is_ok(tmp_path):
    with make_client(tmp_path, Agent()) as client:
        assert client.get("/queries/nope").status_code == 404
        assert client.get("/health").json() == {"status": "ok"}


def test_root_serves_the_web_ui(tmp_path):
    with make_client(tmp_path, Agent()) as client:
        res = client.get("/")
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/html")
        assert "vegaEmbed" in res.text and "/queries" in res.text


def test_stats_step_is_saved_next_to_trials(tmp_path):
    plan = SearchPlan(
        steps=[{"endpoint": "studies", "label": "Nivolumab", "drugs": ["nivolumab"]},
               {"endpoint": "stats/field/values", "label": "All trials", "fields": ["Phase"]}],
        rationale="Nivolumab trials and the registry-wide phase split.",
    )  # fmt: skip
    chart = ChartPlan(intent="distribution", chart_type="bar_chart", title="Nivolumab trials by phase", x=Dimension.PHASE)
    with make_client(tmp_path, Agent(plan=plan, chart=chart)) as client:
        task_id = client.post("/queries", json={"query": "Nivolumab trials by phase"}).json()["task_id"]
        done = wait_until_finished(client, task_id)

    assert done["status"] == "succeeded"
    assert done["progress"]["message"] == "Saved 2 trials and 1 registry stats result"
    steps = json.loads((tmp_path / task_id / "fetch-1" / "steps.json").read_text())
    assert steps[1] == {
        "label": "All trials",
        "endpoint": "stats/field/values",
        "params": {"fields": "Phase"},
        "stats_file": "stats/2-all-trials.json",
        "incomplete_fields": [],
    }
    saved = json.loads((tmp_path / task_id / "fetch-1" / steps[1]["stats_file"]).read_text())
    assert saved[0]["topValues"][0] == {"value": "PHASE2", "studiesCount": 5}


def test_committed_openapi_schema_matches_the_code():
    """docs/api/openapi.json is what the README points readers to; regenerate it with
    scripts/export_openapi.py when the API changes."""
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root / "scripts"))
    from export_openapi import OUT, schema

    assert json.loads(OUT.read_text()) == json.loads(json.dumps(schema())), "run scripts/export_openapi.py"
