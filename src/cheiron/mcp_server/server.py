"""cheiron as an MCP server: Claude plans and picks the chart, code fetches, counts and cites.

    start_query(question, filters)  -> query_id + how to plan the search (specs/query-agent.yaml)
    fetch_data(query_id, plan)      -> code runs the SearchPlan against ClinicalTrials.gov
    describe_data(query_id)         -> profile of the fetched data + how to choose the chart
                                       (specs/chart-planner.yaml), on the first call
    read_api_docs(page)             -> one page of the ClinicalTrials.gov API reference
    read_reference(page)            -> one page of the chart planner's references
    build_chart(query_id, chart)    -> code checks the ChartPlan, builds the chart with citations,
                                       saves it; renders inline in hosts with MCP Apps
                                       (ui://cheiron/chart), else returns a localhost link
    get_result(result_id)           -> a saved answer, for the inline page (app-only)

Run:  cheiron-mcp            (stdio, launched by Claude)
      cheiron-mcp serve      (only the local page, to reopen saved answers)
"""

import argparse
import asyncio
import json
import logging
import re
import sys
from contextlib import AsyncExitStack, asynccontextmanager
from functools import cache
from pathlib import Path
from typing import Annotated, Any

import yaml
from mcp.server.apps import Apps, client_supports_apps
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import CallToolResult, TextContent
from pydantic import Field, ValidationError

from cheiron.agents.api_docs import ApiDocs, load_api_docs, snapshot_api_docs
from cheiron.agents.chart_planner import REFERENCES
from cheiron.fetch.client import CtgovClient
from cheiron.mcp_server.results import ResultStore
from cheiron.mcp_server.session import Queries, QueryError
from cheiron.mcp_server.web import LocalWeb, serve
from cheiron.models.request import QueryRequest, RecruitmentStatus, TrialPhase
from cheiron.models.response import QueryResponse
from cheiron.workflow.pipeline import QueryWorkflow
from cheiron.workflow.plans import ChartPlan, SearchPlan

SPECS = Path(__file__).parent.parent / "agents" / "specs"
WEB = Path(__file__).parent.parent / "web"
CHART_UI = "ui://cheiron/chart"
RESPONSE_META_KEY = "cheiron/response"  # the full answer, for the inline page only (not the model)
SUMMARY_ROWS = 25
SOURCES = {"citations", "nct_ids"}  # for the page; the model gets the counts only  # data rows quoted back to the model, so it can describe the chart

log = logging.getLogger("cheiron.mcp")

INSTRUCTIONS = """\
cheiron answers questions about clinical trials registered on ClinicalTrials.gov with one chart,
where code fetches every matching trial and every number cites the trials behind it.
Use it for questions about trial counts, phases, sponsors, drugs, conditions, countries, trends,
comparisons or networks. Start with start_query and follow the procedure it returns. Never state a
number that did not come from a tool result.
"""

# The specs were written for the web service's two agents; inside Claude one model plays both.
QUERY_PREFACE = """\
You are doing the query agent's job below, with these differences:
- There is no plan_chart tool. When the instructions say to call plan_chart, call describe_data
  (its first answer includes the chart planner's instructions), choose the chart yourself following
  them, and call build_chart with the ChartPlan. If build_chart returns a problem, fix the plan or
  fetch again, as the instructions say for plan_chart.
- "Answer unanswerable" means: stop and tell the user why registry data cannot answer it.
- Pass the query_id below to every tool.

"""
CHART_PREFACE = """\
Choosing the chart (the chart planner's instructions; you play the chart planner now). Your
"answer" is a build_chart call with the ChartPlan; "unanswerable" means telling the user why.

"""


@cache
def _instructions(name: str) -> str:
    return yaml.safe_load((SPECS / f"{name}.yaml").read_text())["instructions"]


class Cheiron:
    """Everything the tools share, created once per process."""

    def __init__(self, queries: Queries, store: ResultStore, web: LocalWeb):
        self.queries = queries
        self.store = store
        self.web = web
        self.docs: ApiDocs | None = None
        self.chart_guide_sent: set[str] = set()

    async def api_docs(self) -> ApiDocs:
        if self.docs is None:
            try:
                self.docs = await load_api_docs()
            except Exception:  # offline: the bundled snapshot
                log.exception("could not load the live API reference; using the snapshot")
                self.docs = snapshot_api_docs()
        return self.docs


_state: Cheiron | None = None


def _cheiron() -> Cheiron:
    if _state is None:
        raise ToolError("cheiron is still starting; try again in a moment.")
    return _state


@asynccontextmanager
async def lifespan(server: MCPServer):
    global _state
    async with AsyncExitStack() as stack:
        client = await stack.enter_async_context(CtgovClient())
        store = ResultStore()
        _state = Cheiron(Queries(QueryWorkflow(agent=None, source=client)), store, LocalWeb(store))
        try:
            yield {}
        finally:
            _state = None


def _fail(exc: Exception) -> ToolError:
    if isinstance(exc, ValidationError):
        return ToolError(f"Invalid input: {exc}")
    return ToolError(str(exc))


async def start_query(
    question: Annotated[str, Field(description="The user's question, in their words.")],
    drug_name: str | None = None,
    condition: str | None = None,
    sponsor: str | None = None,
    country: str | None = None,
    trial_phase: list[TrialPhase] | None = None,
    recruitment_status: list[RecruitmentStatus] | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
) -> str:
    """Start answering one clinical-trials question. Set a filter only when the user gave it
    explicitly as a constraint; otherwise leave it to the search plan. Returns a query_id and the
    procedure to follow: read it fully before planning the search."""
    try:
        request = QueryRequest(
            query=question,
            drug_name=drug_name,
            condition=condition,
            sponsor=sponsor,
            country=country,
            trial_phase=trial_phase,
            recruitment_status=recruitment_status,
            start_year=start_year,
            end_year=end_year,
        )
    except ValidationError as exc:
        raise _fail(exc) from exc
    session = _cheiron().queries.start(request)
    filters = request.filters()
    lines = [
        f"query_id: {session.id}",
        f"Question: {request.query}",
        "User-supplied filters (code applies all of them): " + (json.dumps(filters) if filters else "none"),
        "",
        QUERY_PREFACE + _instructions("query-agent"),
    ]
    return "\n".join(lines)


async def fetch_data(query_id: str, plan: SearchPlan) -> str:
    """Execute a search plan. Code resolves names to the registry's own, adds the user's fields,
    builds the API calls, fetches every page and keeps the data; you get back how many trials each
    step matched and what each step searched. At most 5 fetches per query."""
    try:
        return json.dumps(await _cheiron().queries.fetch(query_id, plan))
    except QueryError as exc:
        raise _fail(exc) from exc


async def describe_data(query_id: str) -> str:
    """Profile of the latest successful fetch: per field the distinct values, missing trials, top
    values with trial counts, whether a trial can have several values, and per comparison side.
    Never records. The first call also returns how to choose the chart."""
    state = _cheiron()
    try:
        profile = state.queries.describe(query_id)
    except QueryError as exc:
        raise _fail(exc) from exc
    text = "Profile of the fetched data:\n" + profile.model_dump_json(exclude_none=True)
    if query_id not in state.chart_guide_sent:
        state.chart_guide_sent.add(query_id)
        plan = state.queries.get(query_id).outcome.plan
        text += (
            "\n\nSearch plan of the fetched data:\n"
            + plan.model_dump_json(exclude_none=True)
            + "\n\n"
            + CHART_PREFACE
            + _instructions("chart-planner")
        )
    return text


async def read_api_docs(
    page: Annotated[str, Field(description="'fields' (then 'fields/<module>'), 'enums', 'search-areas', 'parameters' or 'essie-syntax'.")],
) -> str:
    """Read one page of the ClinicalTrials.gov API reference, only when the instructions say you
    need it."""
    docs = await _cheiron().api_docs()
    text = docs.page(page)
    if text is None:
        raise ToolError(f"Unknown page {page!r}. Start from: {', '.join(docs.top_level())}")
    return text


async def read_reference(page: Annotated[str, Field(description="e.g. 'networks' or 'examples'.")]) -> str:
    """Read one chart-planning reference page, only when the chart instructions say you need it."""
    available = sorted(p.stem for p in REFERENCES.glob("*.md"))
    name = page.strip().removesuffix(".md").removeprefix("references/")
    if name not in available:
        raise ToolError(f"Unknown reference {page!r}. Available: {', '.join(available)}")
    return (REFERENCES / f"{name}.md").read_text()


async def build_chart(query_id: str, chart: ChartPlan, ctx: Context) -> CallToolResult:
    """Build the chart from the latest successful fetch. Code checks the plan against the data
    (a plan that does not fit comes back with the reason: fix it and call again), counts distinct
    trials, attaches citations and saves the answer. The chart is shown to the user; describe it
    from the summary returned, with no numbers that are not in it."""
    state = _cheiron()
    try:
        response = await state.queries.build(query_id, chart)
    except QueryError as exc:
        raise _fail(exc) from exc
    session = state.queries.get(query_id)
    result_id = state.store.save(session.request, response)
    inline = client_supports_apps(ctx)
    url = None if inline else await asyncio.to_thread(state.web.url_for, result_id)  # Claude Code: a browser tab
    summary = summarize(response, result_id, url, inline)
    return CallToolResult(
        content=[TextContent(type="text", text=summary)],
        _meta={RESPONSE_META_KEY: response.model_dump(mode="json", by_alias=True), "cheiron/result_id": result_id},
    )


async def get_result(result_id: str) -> dict[str, Any]:
    """A saved answer (the full QueryResponse), for the chart page."""
    doc = _cheiron().store.load(result_id)
    if doc is None:
        raise ToolError(f"No saved result {result_id!r}.")
    return doc["response"]


def summarize(response: QueryResponse, result_id: str, url: str | None, inline: bool) -> str:
    """What the model reads: enough to describe the chart and send the user to it, no citations."""
    viz, meta = response.visualization, response.meta
    out: dict[str, Any] = {
        "result_id": result_id,
        "shown_inline": inline,
        "open_in_browser": url,
        "title": viz.title,
        "chart_type": viz.type,
        "interpretation": meta.interpretation,
        "total_trials_matched": meta.total_trials_matched,
        "trials_analyzed": meta.trials_analyzed,
        "data_as_of": meta.data_as_of.isoformat() if meta.data_as_of else None,
        "warnings": meta.warnings,
        "assumptions": meta.assumptions,
        "units": meta.units,
    }
    if viz.type == "network_graph":
        nodes = sorted(viz.data.nodes, key=lambda n: -(n.size or 0))
        out["top_nodes"] = [{"label": n.label, "group": n.group, "trials": n.size} for n in nodes[:SUMMARY_ROWS]]
        out["nodes"], out["edges"] = len(viz.data.nodes), len(viz.data.edges)
    else:
        rows = [{k: v for k, v in row.model_dump(mode="json").items() if k not in SOURCES} for row in viz.data]
        out["rows"] = rows[:SUMMARY_ROWS]
        if len(rows) > SUMMARY_ROWS:
            out["rows_not_shown"] = len(rows) - SUMMARY_ROWS
    where = (
        "The chart is shown inline above."
        if inline
        else f"Give the user this link to the chart, its data and its sources: {url}"
        if url
        else "The local page could not start; the answer is saved as " + result_id
    )
    return where + "\n" + json.dumps(out, ensure_ascii=False)


# --- The inline page --------------------------------------------------------------------------


def chart_page_html() -> str:
    """index.html for the MCP App iframe: the vendored scripts inlined (the sandbox may not load
    CDNs or localhost), plus the MCP Apps SDK, and `data-mode="mcp-app"` so the page waits for the
    tool result instead of showing the question form."""
    html = (WEB / "index.html").read_text()

    def inline(match: re.Match) -> str:
        code = (WEB / "vendor" / match.group(1)).read_text().replace("</script", "<\\/script")
        return f"<script>{code}</script>"

    html = re.sub(r'<script src="/vendor/([\w.-]+)"></script>', inline, html)
    sdk = (WEB / "vendor" / "mcp-apps.js").read_text().replace("</script", "<\\/script")
    html = html.replace("<html lang=\"en\">", '<html lang="en" data-mode="mcp-app">', 1)
    return html.replace("</head>", f"<script>{sdk}</script>\n</head>", 1)


# The Apps extension takes its tools and pages when the server is built, so they come first.
apps = Apps()
apps.tool(resource_uri=CHART_UI, name="build_chart")(build_chart)
apps.add_html_resource(CHART_UI, chart_page_html(), name="cheiron chart", title="cheiron chart", prefers_border=True)
mcp = MCPServer("cheiron", instructions=INSTRUCTIONS, lifespan=lifespan, extensions=[apps], log_level="WARNING")
for tool in (start_query, fetch_data, describe_data, read_api_docs, read_reference):
    mcp.tool()(tool)
mcp.tool(meta={"ui": {"visibility": ["app"]}})(get_result)  # for the chart page, not the model


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="cheiron-mcp", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command")
    serve_cmd = sub.add_parser("serve", help="serve the local page with saved answers (no MCP)")
    serve_cmd.add_argument("--port", type=int, default=None)
    args = parser.parse_args(argv)
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)  # stdout carries the MCP protocol
    if args.command == "serve":
        serve(args.port) if args.port else serve()
        return
    mcp.run()  # stdio


if __name__ == "__main__":
    main()
