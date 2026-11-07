"""The HTTP service end to end, with a fake planner and fake API source; outputs go to a temp folder."""

import json
import time

from fastapi.testclient import TestClient

from cheiron.api.app import create_app
from cheiron.api.outputs import QueryOutputs
from cheiron.api.tasks import TaskStore
from cheiron.fetch.models import DataVersion, Trial
from cheiron.fetch.stats import FieldValuesResponse
from cheiron.workflow import FetchResult, SearchPlan, StatsResult
from cheiron.workflow.errors import UnsupportedQuery
from cheiron.workflow.pipeline import QueryWorkflow

DATA_TS = "2026-11-06T10:00:05"


class Planner:
    def __init__(self, fail: Exception | None = None):
        self.fail = fail

    async def plan(self, request, feedback=None):
        if self.fail:
            raise self.fail
        return SearchPlan(
            steps=[{"endpoint": "studies", "label": "Nivolumab", "params": {"query.intr": "nivolumab"}},
                      {"endpoint": "studies", "label": "Pembrolizumab", "params": {"query.intr": "pembrolizumab"}}],
            rationale="Each drug's trials.",
        )  # fmt: skip


class Source:
    async def data_version(self):
        return DataVersion(api_version="2.0.5", data_timestamp=DATA_TS)

    async def search(self, params, limit=None, on_progress=None):
        n = 2 if params.search["query.intr"] == "nivolumab" else 3
        trials = [Trial(nct_id=f"NCT{i:08d}", phases=["PHASE3"]) for i in range(n)]
        if on_progress:
            on_progress(n, n)
        return FetchResult(trials=trials, total_matched=n)


def make_client(tmp_path, planner):
    async def factory(stack):
        return TaskStore(QueryWorkflow(search_planner=planner, source=Source()), QueryOutputs(tmp_path))

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


def test_submit_poll_and_find_outputs_on_disk(tmp_path):
    with make_client(tmp_path, Planner()) as client:
        submitted = client.post("/queries", json=QUESTION)
        assert submitted.status_code == 202
        task_id = submitted.json()["task_id"]
        assert submitted.headers["location"] == f"/queries/{task_id}"
        done = wait_until_finished(client, task_id)

    assert done["status"] == "succeeded"
    assert done["progress"]["stage"] == "done" and done["progress"]["trials_fetched"] == 5
    folder = tmp_path / task_id  # one folder per query, named by its UUID
    assert sorted(p.name for p in folder.iterdir()) == ["meta.json", "plan.json", "request.json", "steps.json", "trials"]
    assert json.loads((folder / "request.json").read_text()) == QUESTION
    searches = json.loads((folder / "steps.json").read_text())
    assert [s["trials_file"] for s in searches] == ["trials/1-nivolumab.json", "trials/2-pembrolizumab.json"]
    assert searches[0]["params"]["filter.advanced"] == "AREA[Phase](PHASE3)"  # user filter recorded as executed
    assert len(json.loads((folder / searches[1]["trials_file"]).read_text())) == 3
    meta = json.loads((folder / "meta.json").read_text())
    assert meta["status"] == "succeeded" and meta["data_as_of"] == DATA_TS and meta["trials_fetched"] == 5


def test_every_query_gets_its_own_folder(tmp_path):
    with make_client(tmp_path, Planner()) as client:
        ids = [client.post("/queries", json=QUESTION).json()["task_id"] for _ in range(2)]
        for task_id in ids:
            wait_until_finished(client, task_id)
    assert ids[0] != ids[1]
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(ids)


def test_failed_query_keeps_request_and_error_on_disk(tmp_path):
    with make_client(tmp_path, Planner(fail=UnsupportedQuery("Efficacy is not in registry records."))) as client:
        task_id = client.post("/queries", json=QUESTION).json()["task_id"]
        done = wait_until_finished(client, task_id)

    assert done["status"] == "failed"
    assert done["error"] == {"error": "unsupported_query", "message": "Efficacy is not in registry records.", "details": {}}
    folder = tmp_path / task_id
    assert sorted(p.name for p in folder.iterdir()) == ["meta.json", "request.json"]
    assert json.loads((folder / "meta.json").read_text())["error"]["error"] == "unsupported_query"


def test_unexpected_error_is_hidden_behind_a_generic_message(tmp_path):
    with make_client(tmp_path, Planner(fail=RuntimeError("secret internals"))) as client:
        done = wait_until_finished(client, client.post("/queries", json=QUESTION).json()["task_id"])
    assert done["error"]["error"] == "internal_error" and "secret" not in done["error"]["message"]


def test_invalid_request_is_rejected_before_any_task(tmp_path):
    with make_client(tmp_path, Planner()) as client:
        response = client.post("/queries", json={"query": "x", "drugname": "typo"})
    assert response.status_code == 422
    assert not any(tmp_path.iterdir())


def test_unknown_task_is_404_and_health_is_ok(tmp_path):
    with make_client(tmp_path, Planner()) as client:
        assert client.get("/queries/nope").status_code == 404
        assert client.get("/health").json() == {"status": "ok"}


class StatsPlanner:
    async def plan(self, request, feedback=None):
        return SearchPlan(
            steps=[{"endpoint": "stats/field/values", "label": "All trials", "fields": ["Phase"]}],
            rationale="Phase distribution across the whole registry.",
        )


class StatsSource(Source):
    async def fetch_stats(self, step):
        data = FieldValuesResponse.model_validate(
            [{"field": "protocolSection.designModule.phases", "piece": "Phase", "type": "ENUM", "missingStudiesCount": 0,
              "uniqueValuesCount": 2, "topValues": [{"value": "PHASE2", "studiesCount": 5}, {"value": "PHASE3", "studiesCount": 3}]}]
        )  # fmt: skip
        return StatsResult(endpoint=step.endpoint, data=data)


def test_registry_wide_stats_query_saves_a_stats_file_and_no_trials(tmp_path):
    async def factory(stack):
        return TaskStore(QueryWorkflow(search_planner=StatsPlanner(), source=StatsSource()), QueryOutputs(tmp_path))

    with TestClient(create_app(factory)) as client:
        task_id = client.post("/queries", json={"query": "How are all registered trials split by phase?"}).json()["task_id"]
        done = wait_until_finished(client, task_id)

    assert done["status"] == "succeeded" and done["progress"]["message"] == "Saved 1 registry stats result"
    folder = tmp_path / task_id
    assert sorted(p.name for p in folder.iterdir()) == ["meta.json", "plan.json", "request.json", "stats", "steps.json"]
    step = json.loads((folder / "steps.json").read_text())[0]
    assert step == {
        "label": "All trials",
        "endpoint": "stats/field/values",
        "params": {"fields": "Phase"},
        "stats_file": "stats/1-all-trials.json",
        "incomplete_fields": [],
    }
    assert json.loads((folder / step["stats_file"]).read_text())[0]["topValues"][0] == {"value": "PHASE2", "studiesCount": 5}
