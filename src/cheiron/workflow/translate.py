"""Deterministic glue between steps: merging user filters into the plan, and
turning a plan into API parameters. No AI here."""

import re

from cheiron.fetch.models import StudySearchParams, build_advanced_filter
from cheiron.models.request import QueryRequest
from cheiron.workflow.plans import SearchGroup, SearchPlan

# Request field -> SearchGroup field
_GROUP_FIELDS = {"drug_name": "intervention", "condition": "condition", "sponsor": "sponsor", "country": "location"}

_ESSIE_SYNTAX = re.compile(r'["()]|\b(AND|OR|NOT)\b|AREA\[')


def phrase(text: str) -> str:
    """Quote text so the API matches it as a phrase.

    Unquoted, 'multiple sclerosis' also matches 'tuberous sclerosis' (68 vs 55
    trials in a live check). Text that already uses Essie syntax is left alone.
    """
    return text if _ESSIE_SYNTAX.search(text) else f'"{text}"'


def apply_request_filters(plan: SearchPlan, request: QueryRequest) -> tuple[SearchPlan, list[str]]:
    """Structured fields the user sent override what the planner inferred.

    Exception: if the plan compares groups on that very field (e.g. two drugs),
    overriding would erase the comparison, so the plan wins and a warning says so.
    """
    warnings: list[str] = []
    groups = [g.model_copy() for g in plan.groups]
    for req_field, group_field in _GROUP_FIELDS.items():
        value = getattr(request, req_field)
        if value is None:
            continue
        values_in_plan = {getattr(g, group_field) for g in groups}
        if plan.is_comparison and len(values_in_plan) > 1:
            warnings.append(f"Ignored {req_field}={value!r}: the question compares groups by {group_field}.")
            continue
        groups = [g.model_copy(update={group_field: value}) for g in groups]

    update = {"groups": groups}
    if request.trial_phase:
        update["phases"] = request.trial_phase
    if request.recruitment_status:
        update["statuses"] = request.recruitment_status
    if request.start_year:
        update["start_year"] = request.start_year
    if request.end_year:
        update["end_year"] = request.end_year
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
