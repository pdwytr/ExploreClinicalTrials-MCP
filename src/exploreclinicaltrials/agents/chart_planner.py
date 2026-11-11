"""The chart planner: a sub-agent that chooses one chart from a profile of the fetched data.

The query agent calls it through its plan_chart tool. Its input is built by code from what the
run already holds: the question, the user's fields, the latest search plan (with the breakdown the
question asks for), the query agent's brief and the data profile. It never sees records, and its
context holds none of the search work, only the facts the chart depends on.

Spec:    specs/chart-planner.yaml (instructions; Pydantic AI agent spec)
Tools:   read_reference(page)   one page of specs/chart-planner/ (networks, examples, ...)
Output:  ChartPlan, accepted only if code finds it fits the data (check_chart_plan), or Unanswerable.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from pydantic_ai import (
    Agent,
    ModelRetry,
    RunContext,
    ToolOutput,
    UnexpectedModelBehavior,
    capture_run_messages,
)
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models import Model
from pydantic_ai.usage import RunUsage

from exploreclinicaltrials.models.request import QueryRequest
from exploreclinicaltrials.workflow.errors import UnsupportedQuery
from exploreclinicaltrials.workflow.pipeline import check_chart_plan
from exploreclinicaltrials.workflow.plans import (
    ChartPlan,
    DataProfile,
    Dimension,
    SearchPlan,
    Unanswerable,
)
from exploreclinicaltrials.workflow.translate import year_bounds

SPEC = Path(__file__).parent / "specs" / "chart-planner.yaml"
REFERENCES = Path(__file__).parent / "specs" / "chart-planner"


@dataclass
class ChartInput:
    """Everything the chart planner is told: built by code, never chosen by the query agent."""

    request: QueryRequest
    plan: SearchPlan  # the latest successful fetch's plan: what the chart is built from
    profile: DataProfile
    brief: str  # the query agent's note: what the chart must show, what it found on the way


@dataclass
class ChartState:
    input: ChartInput
    warnings: list[str] = field(default_factory=list)
    references_read: list[str] = field(default_factory=list)
    last_problem: str | None = None  # the last reason a chart was sent back


@dataclass
class ChartDecision:
    """One chart planner run: its answer, what it read, and its messages for the trace."""

    output: ChartPlan | Unanswerable | None
    warnings: list[str]
    references_read: list[str]
    messages: list[ModelMessage]
    problem: str | None = None  # set when the planner ran out of retries without a fitting chart


class ChartPlanner:
    def __init__(self, model: Model):
        self._agent = Agent.from_file(
            SPEC,
            model=model,
            output_type=[ToolOutput(ChartPlan, name="chart_plan"), ToolOutput(Unanswerable, name="unanswerable")],
            deps_type=ChartState,
            tools=TOOLS,
        )
        self._agent.output_validator(validate_chart)

    async def decide(self, chart_input: ChartInput, usage: RunUsage | None = None) -> ChartDecision:
        """Run the planner. `usage` is the calling run's, so tokens are counted once for the query."""
        state = ChartState(chart_input)
        with capture_run_messages() as messages:
            try:
                result = await self._agent.run(build_prompt(chart_input), deps=state, usage=usage)
            except UnexpectedModelBehavior as exc:  # out of retries: report the last reason, not a crash
                problem = state.last_problem or str(exc)
                return ChartDecision(None, [], state.references_read, list(messages), problem)
        return ChartDecision(result.output, state.warnings, state.references_read, list(messages))


async def read_reference(ctx: RunContext[ChartState], page: str) -> str:
    """Read one reference page, e.g. 'networks' or 'examples'. Only when the references table says
    you need it."""
    available = sorted(p.stem for p in REFERENCES.glob("*.md"))
    name = page.strip().removesuffix(".md").removeprefix("references/")
    if name not in available:
        raise ModelRetry(f"Unknown reference {page!r}. Available: {', '.join(available)}")
    ctx.deps.references_read.append(name)
    return (REFERENCES / f"{name}.md").read_text()


TOOLS = [read_reference]  # also listed in the spec's metadata (a test checks)


async def validate_chart(ctx: RunContext[ChartState], output: ChartPlan | Unanswerable) -> ChartPlan | Unanswerable:
    """A chart plan is accepted only if it shows the stated breakdown and fits the data (code checks)."""
    if isinstance(output, Unanswerable):
        return output
    state = ctx.deps
    problem = breakdown_problem(state.input.plan, output)
    if problem is None:
        try:
            bounds = year_bounds(state.input.plan, state.input.request)
            state.warnings = check_chart_plan(output, state.input.plan, state.input.profile, bounds)
        except UnsupportedQuery as exc:
            problem = f"This chart does not fit the fetched data: {exc.message}"
    if problem:
        state.last_problem = problem
        raise ModelRetry(problem)
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
            f"Answer unanswerable and say that {what} is not available, instead of charting another field."
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
            f"Chart {asked}, or answer unanswerable if the plan was wrong (the query agent will fetch again)."
        )
    return None


def build_prompt(chart_input: ChartInput) -> str:
    filters = chart_input.request.filters()
    lines = [f"Question: {chart_input.request.query}", ""]
    lines.append("User-supplied filters: " + ("none" if not filters else ""))
    lines += [f"- {name}: {value}" for name, value in filters.items()]
    lines += [
        "",
        f"Query agent's brief: {chart_input.brief.strip() or '(none)'}",
        "",
        "Search plan of the fetched data:",
        chart_input.plan.model_dump_json(exclude_none=True),
        "",
        "Profile of the fetched data:",
        chart_input.profile.model_dump_json(exclude_none=True),
    ]
    return "\n".join(lines)
