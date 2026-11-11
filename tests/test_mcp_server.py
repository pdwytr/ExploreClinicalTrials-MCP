"""studytrials-mcp: the tools Claude drives (start -> fetch -> describe -> build), the inline chart
page, the saved answers and the local page. ClinicalTrials.gov is the workflow tests' FakeSource."""

import asyncio
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from mcp import Client

from studytrials.mcp_server import server
from studytrials.mcp_server.results import ResultStore
from studytrials.mcp_server.web import create_results_app
from studytrials.models.request import QueryRequest
from tests.test_workflow import FOUND, FakeSource

PLAN = {"steps": [{"endpoint": "studies", "label": "Ozempic", "drugs": ["Ozempic"]}], "rationale": "Ozempic trials"}
BY_PHASE = {"intent": "distribution", "chart_type": "bar_chart", "title": "Ozempic trials by phase", "x": "phase"}


@pytest.fixture
def studytrials(monkeypatch, tmp_path):
    """The real MCP server with a fake registry, results under tmp_path, and no real web server."""
    monkeypatch.setenv("STUDYTRIALS_HOME", str(tmp_path))
    source = FakeSource({"Ozempic": FOUND})

    @asynccontextmanager
    async def fake_client():
        yield source

    monkeypatch.setattr(server, "CtgovClient", fake_client)
    monkeypatch.setattr(server.LocalWeb, "url_for", lambda self, rid: f"http://127.0.0.1:8765/?result={rid}")
    return tmp_path


def call(*steps):
    """Run tool calls in one session; each step is (tool, args) or a callable(previous results)."""

    async def go():
        async with Client(server.mcp) as client:
            results = []
            for name, args in steps:
                args = args(results) if callable(args) else args
                results.append(await client.call_tool(name, args))
            return results

    return asyncio.run(go())


def text(result) -> str:
    return "".join(c.text for c in result.content if c.type == "text")


def query_id(results) -> str:
    return text(results[0]).split("\n", 1)[0].removeprefix("query_id: ")


def test_a_question_goes_from_start_to_a_saved_chart(studytrials):
    start, fetched, described, built = call(
        ("start_query", {"question": "Phases of Ozempic trials"}),
        ("fetch_data", lambda r: {"query_id": query_id(r), "plan": PLAN}),
        ("describe_data", lambda r: {"query_id": query_id(r)}),
        ("build_chart", lambda r: {"query_id": query_id(r), "chart": BY_PHASE}),
    )
    assert "There is no plan_chart tool" in text(start)  # the query agent's spec, adapted
    assert '"status": "ok"' in text(fetched)
    assert "Choosing the chart" in text(described)  # the chart planner's spec arrives with the profile
    assert not built.is_error, text(built)
    assert "http://127.0.0.1:8765/?result=" in text(built)
    assert '"trial_count": 1' in text(built)  # counted by code, quoted back for the model
    response = built.meta["studytrials/response"]
    assert response["visualization"]["title"] == "Ozempic trials by phase"
    assert response["vega_lite"] is not None
    assert response["visualization"]["data"][0]["citations"]  # sources go to the page, not the model
    assert "citations" not in text(built) and "nct_ids" not in text(built)
    saved = ResultStore(studytrials / "results").load(built.meta["studytrials/result_id"])
    assert saved["request"]["query"] == "Phases of Ozempic trials"


def test_a_chart_that_does_not_fit_comes_back_with_the_reason(studytrials):
    grouped = BY_PHASE | {"chart_type": "grouped_bar_chart", "series": "group"}
    *_, built = call(
        ("start_query", {"question": "Phases of Ozempic trials"}),
        ("fetch_data", lambda r: {"query_id": query_id(r), "plan": PLAN}),
        ("build_chart", lambda r: {"query_id": query_id(r), "chart": grouped}),
    )
    assert built.is_error
    assert "only one search" in text(built)


def test_tools_refuse_to_run_out_of_order(studytrials):
    _, described, built = call(
        ("start_query", {"question": "Phases of Ozempic trials"}),
        ("describe_data", lambda r: {"query_id": query_id(r)}),
        ("build_chart", {"query_id": "q-unknown", "chart": BY_PHASE}),
    )
    assert described.is_error and "fetch_data first" in text(described)
    assert built.is_error and "Unknown or expired query_id" in text(built)


def test_start_query_validates_the_users_filters(studytrials):
    (result,) = call(("start_query", {"question": "Trials since", "start_year": 2020, "end_year": 2010}))
    assert result.is_error
    assert "start_year" in text(result)


def test_build_chart_declares_the_inline_page_and_get_result_is_for_the_page_only(studytrials):
    async def go():
        async with Client(server.mcp) as client:
            tools = {t.name: t for t in (await client.list_tools()).tools}
            page = await client.read_resource(server.CHART_UI)
            return tools, page

    tools, page = asyncio.run(go())
    assert tools["build_chart"].meta["ui"]["resourceUri"] == server.CHART_UI
    assert tools["get_result"].meta["ui"]["visibility"] == ["app"]
    html = page.contents[0].text
    assert page.contents[0].mime_type == "text/html;profile=mcp-app"
    assert 'data-mode="mcp-app"' in html
    assert "window.McpApps" in html and "vegaEmbed" in html
    assert "cdn.jsdelivr.net" not in html and 'src="/vendor/' not in html  # everything inlined


def test_the_local_page_serves_saved_answers(tmp_path):
    from studytrials.models.response import QueryResponse

    store = ResultStore(tmp_path)
    response = QueryResponse.model_validate_json(
        (__import__("pathlib").Path(__file__).parent.parent / "examples" / "2-comparison" / "response.json").read_text()
    )
    result_id = store.save(QueryRequest(query="Compare phases"), response)
    web = TestClient(create_results_app(store), base_url="http://127.0.0.1:8765")
    assert web.get("/health").json() == {"status": "ok", "app": "studytrials"}
    assert web.get(f"/results/{result_id}").json()["visualization"]["title"] == response.visualization.title
    assert web.get("/results").json()[0]["query"] == "Compare phases"
    assert web.get("/results/..%2Fsecrets").status_code == 404
    assert web.get("/vendor/vega.min.js").status_code == 200
    assert "openResult" in web.get("/").text


def test_local_page_refuses_other_host_names(tmp_path):
    """DNS rebinding: a website that points its domain at 127.0.0.1 must not read saved answers."""
    store = ResultStore(tmp_path)
    app = create_results_app(store)
    for base in ("http://127.0.0.1:8765", "http://localhost:8766"):
        assert TestClient(app, base_url=base).get("/health").status_code == 200
    rebound = TestClient(app, base_url="http://attacker.example:8765")
    for path in ("/", "/health", "/results", "/results/20260101-000000-abcdef", "/vendor/vega.min.js"):
        assert rebound.get(path).status_code == 400, path


def test_network_summary_names_the_strongest_pairs():
    """'Which drugs are tested together' is answered by the pairs, so the model must get them."""
    import json
    from types import SimpleNamespace

    from studytrials.models.response import Edge, NetworkData, Node

    nodes = [Node(id=f"n{i}", label=name, group="intervention", size=size) for i, (name, size) in
             enumerate([("Dexamethasone", 740), ("Lenalidomide", 374), ("Bortezomib", 301)])]
    edges = [Edge(source="n0", target="n2", weight=150, nct_ids=["NCT1"]), Edge(source="n0", target="n1", weight=200)]
    viz = SimpleNamespace(type="network_graph", title="Drugs tested together", data=NetworkData(nodes=nodes, edges=edges))
    meta = SimpleNamespace(interpretation="", total_trials_matched=4074, trials_analyzed=4074, data_as_of=None,
                           warnings=[], assumptions=[], units={})
    text = server.summarize(SimpleNamespace(visualization=viz, meta=meta), "r1", "http://127.0.0.1:8765/?result=r1", False)
    out = json.loads(text.split("\n", 1)[1])
    assert out["top_pairs"] == [
        {"pair": ["Dexamethasone", "Lenalidomide"], "trials": 200},
        {"pair": ["Dexamethasone", "Bortezomib"], "trials": 150},
    ]
    assert "NCT1" not in text  # sources stay on the page


def test_query_ids_are_opaque_and_expire(monkeypatch):
    """MCP: server-minted handles have enough entropy and a bounded lifetime, and an expired one
    is a tool error that says so."""
    from studytrials.mcp_server import session as sessions

    clock = [1000.0]
    monkeypatch.setattr(sessions.time, "monotonic", lambda: clock[0])
    queries = sessions.Queries(workflow=None)
    first = queries.start(QueryRequest(query="Phases of melanoma trials"))
    assert len(first.id) == len("q-") + 32 and first.id != queries.start(QueryRequest(query="again")).id
    assert queries.get(first.id) is first
    clock[0] += sessions.QUERY_TTL_SECONDS + 1
    with pytest.raises(sessions.QueryError, match="expired"):
        queries.get(first.id)
    with pytest.raises(sessions.QueryError, match="Unknown or expired"):
        queries.get(first.id)  # forgotten once expired
    queries.start(QueryRequest(query="new"))
    assert all(not s.expired(clock[0]) for s in queries._sessions.values())  # expired ones are dropped


def test_annotations_say_what_each_tool_does():
    async def go():
        async with Client(server.mcp) as client:
            return {t.name: t.annotations for t in (await client.list_tools()).tools}, client

    tools, _ = asyncio.run(go())
    assert tools["build_chart"].read_only_hint is False and tools["build_chart"].destructive_hint is False
    assert all(a.read_only_hint for name, a in tools.items() if name != "build_chart")
    assert tools["fetch_data"].open_world_hint and not tools["build_chart"].open_world_hint
