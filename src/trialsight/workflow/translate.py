"""Deterministic glue between steps: turning the agent's plan into executable API calls
(see intent.py), and summarising what was fetched. No AI here."""

import logging
from dataclasses import dataclass, field

from trialsight.fetch.endpoints import FieldSizesStep, FieldValuesStep, RecordSizeStep, StudiesStep, StudyStep
from trialsight.fetch.models import StudySearchParams
from trialsight.models.request import QueryRequest
from trialsight.workflow.intent import Resolver, compile_step, describe, effective_periods, merge_request, resolve_plan
from trialsight.workflow.plans import SearchPlan

log = logging.getLogger(__name__)

# (label, what to execute): a compiled /studies search, or another endpoint's step.
PreparedStep = tuple[str, StudySearchParams | StudyStep | FieldValuesStep | FieldSizesStep | RecordSizeStep]


@dataclass
class PreparedPlan:
    """A plan ready to run: every step compiled, plus what the reader must be told about it."""

    steps: list[PreparedStep]
    warnings: list[str] = field(default_factory=list)  # -> meta.warnings
    notes: list[str] = field(default_factory=list)  # -> meta.assumptions (resolutions, replaced terms)
    descriptions: list[str] = field(default_factory=list)  # -> meta.interpretation, one per studies step


async def prepare_plan(plan: SearchPlan, request: QueryRequest, resolver: Resolver) -> PreparedPlan:
    """Merge the user's fields, resolve names to the registry's own, compile the API parameters.
    Raises InvalidSearch when the plan conflicts with the user's fields (sent back to the agent)."""
    merged, warnings, notes = merge_request(plan, request)
    resolved, resolve_warnings, resolve_notes = await resolve_plan(merged, resolver)
    steps: list[PreparedStep] = [
        (s.label, compile_step(resolved[s.label], request) if isinstance(s, StudiesStep) else s) for s in merged.steps
    ]
    descriptions = [describe(label, r, request) for label, r in resolved.items()]
    return PreparedPlan(steps, warnings + resolve_warnings, notes + resolve_notes, descriptions)


def step_summary(label: str, target) -> dict:
    """One executed step as {label, endpoint, params}: exactly what was sent (rerunnable as-is)."""
    if isinstance(target, StudySearchParams):
        summary = {"label": label, "endpoint": "studies", "params": target.search}
        if target.intent is not None:
            summary["intent"] = target.intent
        if target.searched_as:
            summary["searched_as"] = target.searched_as
        return summary
    if isinstance(target, StudyStep):
        return {"label": label, "endpoint": "study", "params": {"nct_id": target.nct_id.upper()}}
    return {"label": label, "endpoint": target.endpoint, "params": target.query_params()}


def filters_summary(prepared: list[PreparedStep]) -> dict:
    """The exact API calls that ran, for meta.filters_applied."""
    return {"steps": [step_summary(label, target) for label, target in prepared]}


def year_bounds(plan: SearchPlan, request: QueryRequest) -> dict[str, tuple[int | None, int | None]]:
    """Per date field, the widest (from, to) years any /studies step was filtered on."""
    bounds: dict[str, tuple[int | None, int | None]] = {}
    for step in plan.steps:
        if not isinstance(step, StudiesStep):
            continue
        for period in effective_periods(step, request):
            lo, hi = bounds.get(period.field, (period.from_year, period.to_year))
            lo = None if lo is None or period.from_year is None else min(lo, period.from_year)
            hi = None if hi is None or period.to_year is None else max(hi, period.to_year)
            bounds[period.field] = (lo, hi)
    return bounds
