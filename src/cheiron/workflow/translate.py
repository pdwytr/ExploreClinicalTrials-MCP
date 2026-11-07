"""Deterministic glue between steps: checking the plan against the user's filters,
and turning a plan into API parameters. No AI here."""

import logging
import re

from cheiron.fetch.models import StudySearchParams, build_advanced_filter
from cheiron.models.request import QueryRequest
from cheiron.workflow.plans import SearchGroup, SearchPlan

log = logging.getLogger(__name__)

# Request field -> SearchGroup field
_GROUP_FIELDS = {"drug_name": "intervention", "condition": "condition", "sponsor": "sponsor", "country": "location"}

_ESSIE_SYNTAX = re.compile(r'["()]|\b(AND|OR|NOT)\b|AREA\[')


def phrase(text: str) -> str:
    """Quote text so the API matches it as a phrase.

    Unquoted, 'multiple sclerosis' also matches 'tuberous sclerosis' (68 vs 55
    trials in a live check). Text that already uses Essie syntax is left alone.
    """
    return text if _ESSIE_SYNTAX.search(text) else f'"{text}"'


def _same(a, b) -> bool:
    if isinstance(a, str) and isinstance(b, str):
        return a.casefold() == b.casefold()
    if isinstance(a, list) and isinstance(b, list):
        return set(a) == set(b)
    return a == b


def enforce_request_filters(plan: SearchPlan, request: QueryRequest) -> tuple[SearchPlan, list[str]]:
    """Check the planner honoured every structured field the user sent; restore any it didn't.

    The planner sees the whole request and decides first; this is the safety net.
    Corrections are logged (they measure planner mistakes); the user's filters
    always end up in the search.

    Exception: if the plan compares groups on that very field (e.g. two drugs),
    restoring would erase the comparison, so the plan stands and a warning says so.

    Returns the checked plan and user-facing warnings.
    """
    warnings: list[str] = []
    groups = list(plan.groups)

    for req_field, group_field in _GROUP_FIELDS.items():
        wanted = getattr(request, req_field)
        if wanted is None:
            continue
        planned = [getattr(g, group_field) for g in groups]
        if plan.is_comparison and len({p.casefold() if p else p for p in planned}) > 1:
            warnings.append(f"Ignored {req_field}={wanted!r}: the question compares groups by {group_field}.")
            continue
        if not all(_same(p, wanted) for p in planned):
            log.info("planner correction: %s %r -> %r", group_field, planned, wanted)
            groups = [g.model_copy(update={group_field: wanted}) for g in groups]

    update: dict = {"groups": groups}
    shared = {
        "phases": request.trial_phase,
        "statuses": request.recruitment_status,
        "start_year": request.start_year,
        "end_year": request.end_year,
    }
    for field, wanted in shared.items():
        if wanted is not None and not _same(getattr(plan, field), wanted):
            log.info("planner correction: %s %r -> %r", field, getattr(plan, field), wanted)
            update[field] = wanted
    return plan.model_copy(update=update), warnings


def search_params_for(plan: SearchPlan, group: SearchGroup) -> StudySearchParams:
    def q(text: str | None) -> str | None:
        return phrase(text) if text else None

    return StudySearchParams(
        condition=q(group.condition),
        intervention=q(group.intervention),
        sponsor=q(group.sponsor),
        location=q(group.location),
        term=group.term,  # free text: left as written
        overall_status=plan.statuses,
        advanced=build_advanced_filter(plan.phases, plan.start_year, plan.end_year),
    )


def filters_summary(plan: SearchPlan) -> dict:
    """What was actually searched, for meta.filters_applied."""
    summary = plan.model_dump(mode="json", exclude={"interpretation", "groups"}, exclude_none=True)
    summary["groups"] = [g.model_dump(exclude_none=True) for g in plan.groups]
    return summary
