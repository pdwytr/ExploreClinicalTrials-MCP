"""The query agent: one Pydantic AI agent that answers a question with one chart plan.

Skills (Agent Skills format, loaded progressively):
  ctgov-search    in the instructions from the start: how to plan API calls
  chart-planning  loaded with load_skill once the data has been described

Tools:
  fetch_data(plan)  code executes the plan (user filters, every page, one data version),
                    keeps the data, and returns only totals and warnings
  describe_data()   code returns a profile of every fetched field; never records
  load_skill(name)  the body of another skill
  read_reference()  one reference file of the ctgov-search skill

The final answer is a ChartPlan (checked by code against the fetched data before it is
accepted) or Unanswerable. Create one QueryAgent per process: each run keeps its own state.
"""

import json
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from pydantic_ai import Agent, ModelRetry, RunContext, capture_run_messages
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider

from cheiron.models.request import QueryRequest
from cheiron.settings import get_settings
from cheiron.workflow.errors import InvalidSearch, NoResults, UnsupportedQuery
from cheiron.workflow.pipeline import FetchOutcome, check_chart_plan
from cheiron.workflow.plans import ChartPlan, DataProfile, Dimension, SearchPlan, StatsResult, Unanswerable
from cheiron.workflow.profile import build_profile
from cheiron.workflow.translate import year_bounds
from cheiron.workflow.steps import AgentResult, FetchRecord, RunLog

SKILLS_DIR = Path(__file__).parent / "skills"
SEARCH_SKILL = "ctgov-search"
FETCH_BUDGET = 5

ROLE = f"""You answer a question about clinical trials with exactly one chart. Work in this order:
1. Write the search plan following the ctgov-search skill below (typed slots: what the question means;
   code builds the API calls), then call fetch_data with it.
2. Call describe_data to see a profile of the latest fetch (you never see the records).
3. If the question depends on something you must find first (e.g. "the sponsor with the most
   melanoma trials", "the drugs most often combined with X"), read it from that profile, then call
   fetch_data again with what you found. Also fetch again if a fetch failed or the data does not fit.
4. Call load_skill("chart-planning") and choose the chart from the latest profile: the chart is
   built from the latest successful fetch, so that fetch must hold everything the chart shows.
5. Answer through a final-result tool: a ChartPlan, or Unanswerable if registry data cannot answer.
You may call fetch_data at most {FETCH_BUDGET} times. Every fetch is recorded and shown to the reader
with your rationale, so state in each plan's rationale what the fetch is for and what you found before."""

Fetch = Callable[[SearchPlan], Awaitable[FetchOutcome]]


@dataclass
class RunState:
    """Per-run state, passed to tools as deps (never shared between runs)."""

    request: QueryRequest
    fetch: Fetch
    outcome: FetchOutcome | None = None
    profile: DataProfile | None = None
    chart_warnings: list[str] = field(default_factory=list)
    fetches: list[FetchRecord] = field(default_factory=list)
    skills_loaded: list[str] = field(default_factory=lambda: [SEARCH_SKILL])
    references_read: list[str] = field(default_factory=list)


def model_from_settings() -> Model:
    """Build the configured model, passing the API key explicitly (from .env or the environment)."""
    settings = get_settings()
    provider, _, name = settings.cheiron_planner_model.partition(":")
    if provider != "openai" or not name:
        raise ValueError(f"Unsupported CHEIRON_PLANNER_MODEL {settings.cheiron_planner_model!r}; use 'openai:<model>'.")
    return OpenAIResponsesModel(name, provider=OpenAIProvider(api_key=settings.openai_api_key.get_secret_value()))


def skill_body(name: str) -> str:
    text = (SKILLS_DIR / name / "SKILL.md").read_text()
    return re.sub(r"^---\n.*?\n---\n", "", text, count=1, flags=re.DOTALL).strip()


def load_instructions() -> str:
    """Role + the ctgov-search skill body, loaded each run so skill edits apply without restarting."""
    return f"{ROLE}\n\n{skill_body(SEARCH_SKILL)}"


class QueryAgent:
    """Implements the workflow's QueryPlanner slot."""

    def __init__(self, model: Model | None = None):
        self._agent = Agent(
            model or model_from_settings(),
            output_type=[ChartPlan, Unanswerable],
            instructions=load_instructions,
            deps_type=RunState,
            name="query_agent",
            retries=3,  # invalid tool calls or chart plans are sent back to the model with the reason
        )
        for tool in (fetch_data, describe_data, load_skill, read_reference):
            self._agent.tool(tool)
        self._agent.output_validator(validate_output)

    async def decide(self, request: QueryRequest, fetch: Fetch, log: RunLog) -> AgentResult:
        state = RunState(request=request, fetch=fetch, fetches=log.fetches)  # fetches are recorded straight into the log
        started = time.perf_counter()
        with capture_run_messages() as messages:
            try:
                result = await self._agent.run(build_prompt(request), deps=state)
            finally:  # also on failure or cancellation, so the caller can save what happened
                log.messages, log.seconds = list(messages), time.perf_counter() - started
        if isinstance(result.output, Unanswerable):
            raise UnsupportedQuery(result.output.reason)
        assert state.outcome is not None and state.profile is not None  # guaranteed by validate_output
        return AgentResult(
            chart=result.output,
            outcome=state.outcome,
            profile=state.profile,
            chart_warnings=state.chart_warnings,
            skills_loaded=state.skills_loaded,
            references_read=state.references_read,
            usage=result.usage,
        )


# --- Tools ----------------------------------------------------------------------------------


async def fetch_data(ctx: RunContext[RunState], plan: SearchPlan) -> str:
    """Execute a search plan (see the ctgov-search skill). Code resolves names to the registry's own,
    adds the user's fields, builds the API calls, fetches every page and keeps the data; you get back
    how many trials each step matched and what each step searched."""
    state = ctx.deps
    if len(state.fetches) >= FETCH_BUDGET:
        raise ModelRetry(f"The fetch budget ({FETCH_BUDGET}) is used up. Call describe_data and decide.")
    record = FetchRecord(number=len(state.fetches) + 1, plan=plan)
    state.fetches.append(record)
    left = FETCH_BUDGET - len(state.fetches)
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


async def load_skill(ctx: RunContext[RunState], name: str) -> str:
    """Load another skill's instructions by name, e.g. 'chart-planning'."""
    available = sorted(p.parent.name for p in SKILLS_DIR.glob("*/SKILL.md"))
    if name not in available:
        raise ModelRetry(f"Unknown skill {name!r}. Available: {', '.join(available)}")
    if name not in ctx.deps.skills_loaded:
        ctx.deps.skills_loaded.append(name)
    return skill_body(name)


async def read_reference(ctx: RunContext[RunState], path: str, skill: str = SEARCH_SKILL) -> str:
    """Read one reference file of a skill, e.g. 'references/enums.md' (ctgov-search, the default) or
    skill='chart-planning', path='references/networks.md'. Only when that skill's references table
    says you need it."""
    skills = sorted(p.parent.name for p in SKILLS_DIR.glob("*/SKILL.md"))
    if skill not in skills:
        raise ModelRetry(f"Unknown skill {skill!r}. Available: {', '.join(skills)}")
    root = SKILLS_DIR / skill
    available = sorted(p.relative_to(root).as_posix() for p in (root / "references").rglob("*.md"))
    if path not in available:
        top_level = [a for a in available if a.count("/") == 1]
        if skill == SEARCH_SKILL:
            top_level.append("references/data-structure/index.md")
        raise ModelRetry(f"Unknown reference {path!r} in {skill}. Start from: {', '.join(top_level)}")
    ctx.deps.references_read.append(path if skill == SEARCH_SKILL else f"{skill}/{path}")
    return (root / path).read_text()


# --- Final answer check ---------------------------------------------------------------------------


async def validate_output(ctx: RunContext[RunState], output: ChartPlan | Unanswerable) -> ChartPlan | Unanswerable:
    """A chart plan is accepted only if it fits the data actually fetched (checked by code)."""
    if isinstance(output, Unanswerable):
        return output
    state = ctx.deps
    if state.outcome is None or state.profile is None:
        raise ModelRetry("Fetch the data (fetch_data) and look at it (describe_data) before choosing a chart.")
    problem = breakdown_problem(state.outcome.plan, output)
    if problem:
        raise ModelRetry(problem)
    try:
        bounds = year_bounds(state.outcome.plan, state.request)
        state.chart_warnings = check_chart_plan(output, state.outcome.plan, state.profile, bounds)
    except UnsupportedQuery as exc:
        raise ModelRetry(f"This chart does not fit the fetched data: {exc.message}") from exc
    return output


def breakdown_problem(plan: SearchPlan, chart: ChartPlan) -> str | None:
    """The chart must show the breakdown the plan said the question asks for. A breakdown the
    system cannot chart must be refused, never answered with the nearest field it has."""
    asked = (plan.breakdown or "").strip()
    if not asked:
        return None
    if asked.lower().startswith("unsupported"):
        what = asked.split(":", 1)[1].strip() if ":" in asked else "that breakdown"
        return (
            f"The plan says the question asks for a breakdown by {what}, which registry data here cannot chart. "
            f"Answer Unanswerable and say that {what} is not available, instead of charting another field."
        )
    shown = {d.value for d in (chart.x, chart.series, chart.y) if d is not None}
    parts = {p.strip() for p in re.split(r"\s+x\s+", asked)}  # a network names both node kinds
    unknown = sorted(parts - {d.value for d in Dimension})
    if unknown:
        return (
            f"breakdown {asked!r}: {unknown} is not a chartable field; use {[d.value for d in Dimension]}, "
            "'<field> x <field>' for a network, or 'unsupported: <what>'."
        )
    if not parts <= shown:
        return (
            f"The plan says the question asks for a breakdown by {asked}, but the chart shows {sorted(shown)}. "
            f"Chart {asked}, or fetch again with a corrected breakdown if the plan was wrong."
        )
    return None


def build_prompt(request: QueryRequest) -> str:
    lines = [f"Question: {request.query}", ""]
    filters = request.filters()
    if filters:
        lines.append("User-supplied filters (apply all of them):")
        lines += [f"- {name}: {value}" for name, value in filters.items()]
    else:
        lines.append("User-supplied filters: none")
    return "\n".join(lines)
