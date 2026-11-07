"""Agent 1, the search planner: question -> ClinicalTrials.gov searches (or unanswerable).

A Pydantic AI agent that loads the ctgov-search skill at run time:
  - SKILL.md body  -> the agent's instructions
  - references/*   -> read on demand through the `read_reference` tool

Model: set CHEIRON_PLANNER_MODEL (e.g. "openai:<model-name>") and OPENAI_API_KEY,
or pass a model to SearchPlannerAgent (tests pass a fake one).
"""

import os
import re
from pathlib import Path

from pydantic_ai import Agent, ModelRetry
from pydantic_ai.models import Model

from cheiron.models.request import QueryRequest
from cheiron.workflow.errors import UnsupportedQuery
from cheiron.workflow.plans import SearchDecision, SearchPlan, Unanswerable

SKILL_DIR = Path(__file__).parent / "skills" / "ctgov-search"
MODEL_ENV = "CHEIRON_PLANNER_MODEL"

ROLE = (
    "You are the search planner of a clinical-trials question-answering service. "
    "Follow the skill below. Answer only through a final-result tool, never in plain text."
)


class SearchPlannerAgent:
    """Implements the workflow's SearchPlanner slot."""

    def __init__(self, model: Model | str | None = None):
        model = model or os.environ.get(MODEL_ENV)
        if not model:
            raise ValueError(f"No model: pass one or set {MODEL_ENV} (e.g. 'openai:<model-name>').")
        self.references_read: list[str] = []  # reference files opened in the last run
        self._agent = Agent(
            model,
            output_type=[SearchDecision, Unanswerable],
            instructions=self._instructions,
            name="search_planner",
            retries=2,  # invalid tool calls or plans are sent back to the model with the error
        )
        self._agent.tool_plain(self.read_reference)

    def _instructions(self) -> str:
        """SKILL.md body, loaded each run so edits to the skill apply without restarting."""
        text = (SKILL_DIR / "SKILL.md").read_text()
        body = re.sub(r"^---\n.*?\n---\n", "", text, count=1, flags=re.DOTALL)
        return f"{ROLE}\n\n{body.strip()}"

    def read_reference(self, path: str) -> str:
        """Read one reference file of the skill, e.g. 'references/fields.md'. Only open a file when the
        skill's 'References: read only when needed' table says the question needs it."""
        available = sorted(f"references/{p.name}" for p in (SKILL_DIR / "references").glob("*.md"))
        if path not in available:
            raise ModelRetry(f"Unknown reference {path!r}. Available: {', '.join(available)}")
        self.references_read.append(path)
        return (SKILL_DIR / path).read_text()

    async def decide(self, request: QueryRequest, feedback: list[str] | None = None) -> SearchDecision | Unanswerable:
        self.references_read = []
        result = await self._agent.run(build_prompt(request, feedback))
        return result.output

    async def plan(self, request: QueryRequest, feedback: list[str] | None = None) -> SearchPlan:
        decision = await self.decide(request, feedback)
        if isinstance(decision, Unanswerable):
            raise UnsupportedQuery(decision.reason)
        return decision.plan


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
