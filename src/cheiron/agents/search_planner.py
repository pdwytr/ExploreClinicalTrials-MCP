"""Agent 1, the search planner: question -> ClinicalTrials.gov searches (or unanswerable).

A Pydantic AI agent that loads the ctgov-search skill at run time:
  - SKILL.md body  -> the agent's instructions
  - references/*   -> read on demand through the `read_reference` tool

Create one SearchPlannerAgent per process and reuse it: each run is independent and
keeps its own state, so concurrent requests are safe.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import RunUsage

from cheiron.models.request import QueryRequest
from cheiron.settings import get_settings
from cheiron.workflow.errors import UnsupportedQuery
from cheiron.workflow.plans import SearchDecision, SearchPlan, Unanswerable

SKILL_DIR = Path(__file__).parent / "skills" / "ctgov-search"

ROLE = (
    "You are the search planner of a clinical-trials question-answering service. "
    "Follow the skill below. Answer only through a final-result tool, never in plain text."
)


@dataclass
class RunState:
    """Per-run state, passed to tools as deps (never shared between runs)."""

    references_read: list[str] = field(default_factory=list)


@dataclass
class PlannerResult:
    decision: SearchDecision | Unanswerable
    references_read: list[str]
    usage: RunUsage


def model_from_settings() -> Model:
    """Build the configured model, passing the API key explicitly (from .env or the environment)."""
    settings = get_settings()
    provider, _, name = settings.cheiron_planner_model.partition(":")
    if provider != "openai" or not name:
        raise ValueError(f"Unsupported CHEIRON_PLANNER_MODEL {settings.cheiron_planner_model!r}; use 'openai:<model>'.")
    return OpenAIResponsesModel(name, provider=OpenAIProvider(api_key=settings.openai_api_key.get_secret_value()))


class SearchPlannerAgent:
    """Implements the workflow's SearchPlanner slot."""

    def __init__(self, model: Model | None = None):
        self._agent = Agent(
            model or model_from_settings(),
            output_type=[SearchDecision, Unanswerable],
            instructions=load_instructions,
            deps_type=RunState,
            name="search_planner",
            retries=2,  # invalid tool calls or plans are sent back to the model with the error
        )
        self._agent.tool(read_reference)

    async def decide(self, request: QueryRequest, feedback: list[str] | None = None) -> PlannerResult:
        state = RunState()
        result = await self._agent.run(build_prompt(request, feedback), deps=state)
        return PlannerResult(result.output, state.references_read, result.usage)

    async def plan(self, request: QueryRequest, feedback: list[str] | None = None) -> SearchPlan:
        decision = (await self.decide(request, feedback)).decision
        if isinstance(decision, Unanswerable):
            raise UnsupportedQuery(decision.reason)
        return decision.plan


def load_instructions() -> str:
    """SKILL.md body, loaded each run so edits to the skill apply without restarting."""
    text = (SKILL_DIR / "SKILL.md").read_text()
    body = re.sub(r"^---\n.*?\n---\n", "", text, count=1, flags=re.DOTALL)
    return f"{ROLE}\n\n{body.strip()}"


def read_reference(ctx: RunContext[RunState], path: str) -> str:
    """Read one reference file of the skill, e.g. 'references/fields.md'. Only open a file when the
    skill's 'References: read only when needed' table says the question needs it."""
    available = sorted(f"references/{p.name}" for p in (SKILL_DIR / "references").glob("*.md"))
    if path not in available:
        raise ModelRetry(f"Unknown reference {path!r}. Available: {', '.join(available)}")
    ctx.deps.references_read.append(path)
    return (SKILL_DIR / path).read_text()


def build_prompt(request: QueryRequest, feedback: list[str] | None = None) -> str:
    lines = [f"Question: {request.query}", ""]
    filters = request.filters()
    if filters:
        lines.append("User-supplied filters (apply all of them):")
        lines += [f"- {name}: {value}" for name, value in filters.items()]
    else:
        lines.append("User-supplied filters: none")
    if feedback:
        lines += ["", "Your previous plan failed. Fix exactly this:"]
        lines += [f"- {item}" for item in feedback]
    return "\n".join(lines)
