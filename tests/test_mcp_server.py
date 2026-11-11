"""cheiron-mcp: the tools Claude drives (start -> fetch -> describe -> build), the inline chart
page, the saved answers and the local page. ClinicalTrials.gov is the workflow tests' FakeSource."""

import asyncio
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from mcp import Client

from cheiron.mcp_server import server
from cheiron.mcp_server.results import ResultStore
from cheiron.mcp_server.web import create_results_app
from cheiron.models.request import QueryRequest
from tests.test_workflow import FOUND, FakeSource

PLAN = {"steps": [{"endpoint": "studies", "label": "Ozempic", "drugs": ["Ozempic"]}], "rationale": "Ozempic trials"}
BY_PHASE = {"intent": "distribution", "chart_type": "bar_chart", "title": "Ozempic trials by phase", "x": "phase"}


@pytest.fixture
def cheiron(monkeypatch, tmp_path):
    """The real MCP server with a fake registry, results under tmp_path, and no real web server."""
    monkeypatch.setenv("CHEIRON_HOME", str(tmp_path))
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


def test_a_question_goes_from_start_to_a_saved_chart(cheiron):
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
    response = built.meta["cheiron/response"]
    assert response["visualization"]["title"] == "Ozempic trials by phase"
    assert response["vega_lite"] is not None
    assert response["visualization"]["data"][0]["citations"]  # sources go to the page, not the model
    assert "citations" not in text(built) and "nct_ids" not in text(built)
    saved = ResultStore(cheiron / "results").load(built.meta["cheiron/result_id"])
    assert saved["request"]["query"] == "Phases of Ozempic trials"


def test_a_chart_that_does_not_fit_comes_back_with_the_reason(cheiron):
    grouped = BY_PHASE | {"chart_type": "grouped_bar_chart", "series": "group"}
    *_, built = call(
        ("start_query", {"question": "Phases of Ozempic trials"}),
        ("fetch_data", lambda r: {"query_id": query_id(r), "plan": PLAN}),
        ("build_chart", lambda r: {"query_id": query_id(r), "chart": grouped}),
    )
    assert built.is_error
    assert "only one search" in text(built)


def test_tools_refuse_to_run_out_of_order(cheiron):
    _, described, built = call(
        ("start_query", {"question": "Phases of Ozempic trials"}),
        ("describe_data", lambda r: {"query_id": query_id(r)}),
        ("build_chart", {"query_id": "q-unknown", "chart": BY_PHASE}),
    )
    assert described.is_error and "fetch_data first" in text(described)
    assert built.is_error and "Unknown query_id" in text(built)


def test_start_query_validates_the_users_filters(cheiron):
    (result,) = call(("start_query", {"question": "Trials since", "start_year": 2020, "end_year": 2010}))
    assert result.is_error
    assert "start_year" in text(result)


def test_build_chart_declares_the_inline_page_and_get_result_is_for_the_page_only(cheiron):
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
    from cheiron.models.response import QueryResponse

    store = ResultStore(tmp_path)
    response = QueryResponse.model_validate_json(
        (__import__("pathlib").Path(__file__).parent.parent / "examples" / "2-comparison" / "response.json").read_text()
    )
    result_id = store.save(QueryRequest(query="Compare phases"), response)
    web = TestClient(create_results_app(store))
    assert web.get("/health").json() == {"status": "ok", "app": "cheiron"}
    assert web.get(f"/results/{result_id}").json()["visualization"]["title"] == response.visualization.title
    assert web.get("/results").json()[0]["query"] == "Compare phases"
    assert web.get("/results/..%2Fsecrets").status_code == 404
    assert web.get("/vendor/vega.min.js").status_code == 200
    assert "openResult" in web.get("/").text
