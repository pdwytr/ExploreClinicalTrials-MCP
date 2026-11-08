"""Deterministic glue between steps: adding the user's structured filters to the
planner's steps, and summarising what was fetched. No AI here."""

import logging
import re

from cheiron.fetch.endpoints import FieldSizesStep, FieldValuesStep, Period, RecordSizeStep, StudiesStep, StudyStep
from cheiron.fetch.models import StudySearchParams, build_advanced_filter, date_range
from cheiron.models.request import QueryRequest
from cheiron.workflow.errors import InvalidSearch
from cheiron.workflow.plans import SearchPlan

log = logging.getLogger(__name__)

# Request field -> API text parameter
_TEXT_FILTERS = {"drug_name": "query.intr", "condition": "query.cond", "sponsor": "query.spons", "country": "query.locn"}

# (label, what to execute): a /studies search with the user's filters added, or another endpoint's step.
PreparedStep = tuple[str, StudySearchParams | StudyStep | FieldValuesStep | FieldSizesStep | RecordSizeStep]


def phrase(text: str) -> str:
    """Quote a user value so the API matches it as a phrase and never reads it as syntax.

    Unquoted, 'multiple sclerosis' also matches 'tuberous sclerosis' (68 vs 55
    trials in a live check). Inner double quotes are dropped: they would end the phrase.
    """
    return '"' + text.replace('"', "").strip() + '"'


def _norm(expression: str) -> str:
    """Ignore parentheses and spaces when checking whether a filter is already present."""
    return re.sub(r"[()\s]", "", expression)


def _bare(text: str) -> str:
    return " ".join(text.replace('"', " ").split()).casefold()


def _same_term(planner_value: str, user_value: str) -> bool:
    """The planner searched exactly the user's term (ignoring quotes, case and spacing). Only then is
    the user's filter already applied: a value that merely *contains* it (e.g. an OR) is wider."""
    return _bare(planner_value) == _bare(user_value)


def _and(existing: str | None, addition: str) -> str:
    return f"({existing}) AND {addition}" if existing else addition


def apply_request_filters(plan: SearchPlan, request: QueryRequest) -> tuple[list[PreparedStep], list[str]]:
    """Add every structured field the user sent to every /studies step, so filters are guaranteed.

    - Text fields (drug, condition, sponsor, country) are AND-ed onto the matching
      parameter, unless the planner searched exactly that term (an OR containing it is wider).
    - Phases are AND-ed onto filter.advanced, unless it is exactly that phase filter.
    - Years: each step's period becomes a RANGE on its date field. The user's start_year /
      end_year are authoritative: they replace any start-date period the planner wrote.
    - Statuses replace filter.overallStatus (the user's explicit choice wins).
    Exception: if the steps compare sides on that very parameter and the user's value is one
    of the sides (e.g. drug_name=X, "compare X with Y"), AND-ing it onto every side would erase
    the comparison, so it is skipped with a user-facing warning. If the user's value is none of
    the sides, the comparison cannot replace it: it is AND-ed onto every side, with a warning.

    Registry-wide steps (/stats/*) cannot filter, so a plan using them while the user
    sent filters is rejected with InvalidSearch: the planner gets that as feedback.

    A single-study lookup is not filtered either; the user gets a warning.

    Returns the executable steps (in plan order) and warnings.
    """
    warnings: list[str] = []
    if request.filters():
        unfilterable = [s.endpoint for s in plan.steps if s.endpoint.startswith("stats/")]
        if unfilterable:
            raise InvalidSearch(
                f"The user supplied filters {request.filters()}, but {unfilterable} cover the whole registry "
                "and cannot apply them. Use 'studies' steps for filtered questions."
            )
        if any(isinstance(s, StudyStep) for s in plan.steps):
            warnings.append("Filters do not apply to a lookup of one trial by NCT number.")

    studies = [s for s in plan.steps if isinstance(s, StudiesStep)]
    all_params = [dict(s.params) for s in studies]

    for req_field, api_param in _TEXT_FILTERS.items():
        wanted = getattr(request, req_field)
        if wanted is None:
            continue
        values = {p.get(api_param, "").casefold() for p in all_params}
        if plan.is_comparison and len(values) > 1:
            if any(_same_term(p.get(api_param, ""), wanted) for p in all_params):
                warnings.append(f"Ignored {req_field}={wanted!r}: the question compares searches by {api_param}.")
                continue
            warnings.append(f"{req_field}={wanted!r} was applied to every compared side.")
        for p in all_params:
            if not _same_term(p.get(api_param, ""), wanted):
                log.info("added user filter: %s += %r", api_param, wanted)
                p[api_param] = _and(p.get(api_param), phrase(wanted))

    advanced = build_advanced_filter(request.trial_phase)
    statuses = "|".join(s.value for s in request.recruitment_status) if request.recruitment_status else None
    for step, p in zip(studies, all_params):
        if advanced and _norm(advanced) != _norm(p.get("filter.advanced", "")):
            p["filter.advanced"] = _and(p.get("filter.advanced"), advanced)
        for period in effective_periods(step, request):
            p["filter.advanced"] = _and(p.get("filter.advanced"), date_range(period.field, period.from_year, period.to_year))
        if statuses and p.get("filter.overallStatus") != statuses:
            log.info("user status filter replaces %r", p.get("filter.overallStatus"))
            p["filter.overallStatus"] = statuses

    filtered = iter(StudySearchParams(search=p) for p in all_params)
    prepared: list[PreparedStep] = [
        (s.label, next(filtered) if isinstance(s, StudiesStep) else s) for s in plan.steps
    ]
    return prepared, warnings


def step_summary(label: str, target) -> dict:
    """One executed step as {label, endpoint, params}: exactly what was sent (rerunnable as-is)."""
    if isinstance(target, StudySearchParams):
        return {"label": label, "endpoint": "studies", "params": target.search}
    if isinstance(target, StudyStep):
        return {"label": label, "endpoint": "study", "params": {"nct_id": target.nct_id.upper()}}
    return {"label": label, "endpoint": target.endpoint, "params": target.query_params()}


def filters_summary(prepared: list[PreparedStep]) -> dict:
    """The exact API calls that ran, for meta.filters_applied."""
    return {"steps": [step_summary(label, target) for label, target in prepared]}


def effective_periods(step: StudiesStep, request: QueryRequest) -> list[Period]:
    """The periods a /studies step is actually filtered on. The user's start_year / end_year
    replace the planner's start-date period; a completion-date period is kept alongside."""
    periods = []
    if request.start_year or request.end_year:
        if step.period and step.period.field == "start":
            log.info("user years replace the planner's start period %s", step.period)
        periods.append(Period(field="start", from_year=request.start_year, to_year=request.end_year))
    if step.period and not (periods and step.period.field == "start"):
        periods.append(step.period)
    return periods


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
