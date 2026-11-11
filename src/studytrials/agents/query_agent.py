"""The query agent: plans and fetches the data for a question, then has the chart planner chart it.

Spec:    specs/query-agent.yaml (instructions; Pydantic AI agent spec)
Tools:
  fetch_data(plan)       code executes the plan (user filters, every page, one data version),
                         keeps the data, and returns only totals and warnings
  describe_data()        code returns a profile of every fetched field; never records
  read_api_docs(page)    one page of the ClinicalTrials.gov API reference, loaded from the live
                         API when the service started (agents/api_docs.py)
Output (the run ends through one of these):
  plan_chart(brief)      runs the chart planner sub-agent (agents/chart_planner.py) on the latest
                         fetch; its checked ChartPlan is the answer. If it cannot chart the data,
                         the reason comes back here and this agent fetches again or gives up
  unanswerable(reason)   registry data cannot answer the question

Create one QueryAgent per process: each run keeps its own state.
"""

import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from pydantic_ai import Agent, ModelRetry, RunContext, ToolOutput, capture_run_messages
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider

from studytrials.agents.api_docs import ApiDocs, snapshot_api_docs
from studytrials.agents.chart_planner import ChartInput, ChartPlanner
from studytrials.models.request import QueryRequest
from studytrials.settings import get_settings
from studytrials.workflow.errors import InvalidSearch, NoResults, UnsupportedQuery
from studytrials.workflow.pipeline import FetchOutcome
from studytrials.workflow.plans import (
    ChartPlan,
    DataProfile,
    SearchPlan,
    StatsResult,
    Unanswerable,
)
from studytrials.workflow.profile import build_profile
from studytrials.workflow.steps import AgentResult, FetchRecord, RunLog

SPEC = Path(__file__).parent / "specs" / "query-agent.yaml"
FETCH_BUDGET = 5

Fetch = Callable[[SearchPlan], Awaitable[FetchOutcome]]


@dataclass
class RunState:
    """Per-run state, passed to tools as deps (never shared between runs)."""

    request: QueryRequest
    fetch: Fetch
    docs: ApiDocs
    planner: ChartPlanner
    log: RunLog
    outcome: FetchOutcome | None = None
    profile: DataProfile | None = None
    chart_warnings: list[str] = field(default_factory=list)
    docs_read: list[str] = field(default_factory=list)
    references_read: list[str] = field(default_factory=list)


def model_from_settings() -> Model:
    """Build the configured model, passing the API key explicitly (from .env or the environment)."""
    settings = get_settings()
    provider, _, name = settings.studytrials_planner_model.partition(":")
    if provider != "openai" or not name:
        raise ValueError(f"Unsupported STUDYTRIALS_PLANNER_MODEL {settings.studytrials_planner_model!r}; use 'openai:<model>'.")
    return OpenAIResponsesModel(name, provider=OpenAIProvider(api_key=settings.openai_api_key.get_secret_value()))


class QueryAgent:
    """Implements the workflow's QueryPlanner slot. `docs` is the API reference loaded at startup
    (load_api_docs); without it the bundled snapshot is used."""

    def __init__(self, model: Model | None = None, docs: ApiDocs | None = None):
        model = model or model_from_settings()
        self.docs = docs or snapshot_api_docs()
        self._planner = ChartPlanner(model)
        self._agent = Agent.from_file(
            SPEC,
            model=model,
            output_type=[ToolOutput(plan_chart, name="plan_chart"), ToolOutput(Unanswerable, name="unanswerable")],
            deps_type=RunState,
            tools=TOOLS,
        )

    async def decide(self, request: QueryRequest, fetch: Fetch, log: RunLog) -> AgentResult:
        state = RunState(request=request, fetch=fetch, docs=self.docs, planner=self._planner, log=log)
        started = time.perf_counter()
        with capture_run_messages() as messages:
            try:
                result = await self._agent.run(build_prompt(request), deps=state)
            finally:  # also on failure or cancellation, so the caller can save what happened
                log.messages, log.seconds = list(messages), time.perf_counter() - started
        if isinstance(result.output, Unanswerable):
            raise UnsupportedQuery(result.output.reason)
        assert state.outcome is not None and state.profile is not None  # guaranteed by plan_chart
        return AgentResult(
            chart=result.output,
            outcome=state.outcome,
            profile=state.profile,
            chart_warnings=state.chart_warnings,
            docs_read=state.docs_read,
            references_read=state.references_read,
            usage=result.usage,
        )


# --- Tools ----------------------------------------------------------------------------------


async def fetch_data(ctx: RunContext[RunState], plan: SearchPlan) -> str:
    """Execute a search plan. Code resolves names to the registry's own, adds the user's fields,
    builds the API calls, fetches every page and keeps the data; you get back how many trials each
    step matched and what each step searched."""
    state = ctx.deps
    if len(state.log.fetches) >= FETCH_BUDGET:
        raise ModelRetry(f"The fetch budget ({FETCH_BUDGET}) is used up. Call describe_data and decide.")
    record = FetchRecord(number=len(state.log.fetches) + 1, plan=plan)
    state.log.fetches.append(record)
    left = FETCH_BUDGET - len(state.log.fetches)
    started = time.perf_counter()
    try:
        outcome = await state.fetch(plan)
    except (InvalidSearch, NoResults) as exc:
        record.error = exc.message
        record.seconds = time.perf_counter() - started
        return f"Fetch {record.number} failed: {exc.message} Fix the plan and call fetch_data again ({left} call(s) left)."
    record.seconds = time.perf_counter() - started
    stats = [(label, r) for (label, _), r in zip(outcome.prepared, outcome.results) if isinstance(r, StatsResult)]
    profile = build_profile(outcome.trials_by_group, outcome.total_matched, stats, outcome.version.data_timestamp)
    record.outcome, record.profile = outcome, profile
    state.outcome, state.profile = outcome, profile  # the latest successful fetch is what gets charted
    steps = [
        {"label": label, "endpoint": getattr(r, "endpoint", "studies"), "total_matched": getattr(r, "total_matched", None)}
        for (label, _), r in zip(outcome.prepared, outcome.results)
    ]
    return json.dumps(
        {
            "fetch": record.number,
            "fetched": steps,
            "searched": outcome.descriptions,  # what code actually searched, incl. registry names added
            "notes": outcome.notes,
            "warnings": outcome.warnings,
            "fetches_left": left,
            "next": "call describe_data",
        }
    )


async def describe_data(ctx: RunContext[RunState]) -> str:
    """Profile of everything fetched: per field the distinct values, missing trials, top values with
    trial counts, whether a trial can have several values, and per comparison side. Never records."""
    if ctx.deps.profile is None:
        raise ModelRetry("Nothing has been fetched yet: call fetch_data first.")
    return ctx.deps.profile.model_dump_json(exclude_none=True)


async def read_api_docs(ctx: RunContext[RunState], page: str) -> str:
    """Read one page of the ClinicalTrials.gov API reference: 'fields' (then 'fields/<module>'),
    'enums', 'search-areas', 'parameters' or 'essie-syntax'. Only when the reference table says
    you need it."""
    docs = ctx.deps.docs
    text = docs.page(page)
    if text is None:
        raise ModelRetry(f"Unknown page {page!r}. Start from: {', '.join(docs.top_level())}")
    ctx.deps.docs_read.append(page.strip().removesuffix(".md"))
    return text


# --- The answer -------------------------------------------------------------------------------------


async def plan_chart(ctx: RunContext[RunState], brief: str) -> ChartPlan:
    """Have the chart planner choose the chart for the latest successful fetch. `brief`: what the
    chart must show, and anything you found on the way that it depends on. The planner sees the
    question, the user's fields, your latest search plan and its profile. Its chart is your answer."""
    state = ctx.deps
    if state.outcome is None or state.profile is None:
        raise ModelRetry("Fetch the data (fetch_data) and look at it (describe_data) before calling plan_chart.")
    decision = await state.planner.decide(
        ChartInput(request=state.request, plan=state.outcome.plan, profile=state.profile, brief=brief), usage=ctx.usage
    )
    state.log.chart_runs[ctx.tool_call_id or str(len(state.log.chart_runs))] = decision.messages
    state.references_read += decision.references_read
    if isinstance(decision.output, ChartPlan):
        state.chart_warnings = decision.warnings
        return decision.output
    reason = decision.output.reason if decision.output is not None else decision.problem
    raise ModelRetry(
        f"The chart planner could not chart the latest fetch: {reason} "
        "Fetch data that fits (with a corrected breakdown if the plan was wrong), or answer unanswerable."
    )


TOOLS = [fetch_data, describe_data, read_api_docs]  # also listed in the spec's metadata (a test checks)


def build_prompt(request: QueryRequest) -> str:
    lines = [f"Question: {request.query}", ""]
    filters = request.filters()
    if filters:
        lines.append("User-supplied filters (apply all of them):")
        lines += [f"- {name}: {value}" for name, value in filters.items()]
    else:
        lines.append("User-supplied filters: none")
    return "\n".join(lines)
