"""Deterministic glue between steps: checking the plan against the user's filters,
turning a plan into API parameters, and describing what was searched. No AI here."""

import logging
import re

from cheiron.fetch.models import StudySearchParams, build_advanced_filter
from cheiron.models.request import QueryRequest
from cheiron.workflow.plans import SearchGroup, SearchPlan, SearchTerms

log = logging.getLogger(__name__)

# Request field -> SearchGroup term list
_GROUP_FIELDS = {"drug_name": "interventions", "condition": "conditions", "sponsor": "sponsors", "country": "locations"}


# --- Plan -> API parameters ----------------------------------------------------------


def phrase(text: str) -> str:
    """Quote text so the API matches it as a phrase, and so it can never be read as syntax.

    Unquoted, 'multiple sclerosis' also matches 'tuberous sclerosis' (68 vs 55
    trials in a live check). Inner double quotes are dropped: they would end the phrase.
    """
    return '"' + text.replace('"', "").strip() + '"'


def any_of(terms: list[str]) -> str | None:
    """['asthma', 'COPD'] -> '"asthma" OR "COPD"'."""
    return " OR ".join(phrase(t) for t in terms) or None


def search_params_for(plan: SearchPlan, group: SearchGroup) -> StudySearchParams:
    return StudySearchParams(
        condition=any_of(group.conditions),
        intervention=any_of(group.interventions),
        sponsor=any_of(group.sponsors),
        location=any_of(group.locations),
        term=any_of(group.keywords),
        overall_status=plan.statuses,
        advanced=build_advanced_filter(
            plan.phases,
            plan.start_year,
            plan.end_year,
            study_types=plan.study_types,
            intervention_types=plan.intervention_types,
            sponsor_classes=plan.sponsor_classes,
            age_groups=plan.age_groups,
        ),
    )


# --- Planner output vs the user's structured fields -------------------------------------


def _casefold_set(terms: list[str]) -> frozenset[str]:
    return frozenset(t.casefold() for t in terms)


def _same(a, b) -> bool:
    if isinstance(a, list) and isinstance(b, list):
        return set(a) == set(b)
    return a == b


def enforce_request_filters(plan: SearchPlan, request: QueryRequest) -> tuple[SearchPlan, list[str]]:
    """Check the planner honoured every structured field the user sent; restore any it didn't.

    The planner sees the whole request and decides first; this is the safety net.
    A text field is honoured when every group searches for that term (case-insensitive).
    Corrections are logged (they measure planner mistakes); the user's filters
    always end up in the search.

    Exception: if the plan compares groups on that very list (e.g. two drugs),
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
        if plan.is_comparison and len({_casefold_set(p) for p in planned}) > 1:
            warnings.append(f"Ignored {req_field}={wanted!r}: the question compares groups by {group_field}.")
            continue
        if not all(wanted.casefold() in _casefold_set(p) for p in planned):
            log.info("planner correction: %s %r -> %r", group_field, planned, [wanted])
            groups = [g.model_copy(update={group_field: [wanted]}) for g in groups]

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


# --- Describing the search (meta) ---------------------------------------------------------


def _words(values) -> str:
    """[PHASE2, PHASE3] -> 'phase 2 or phase 3'; [NOT_YET_RECRUITING] -> 'not yet recruiting'."""
    return " or ".join(re.sub(r"phase(\d)", r"phase \1", v.value.replace("_", " ").lower()) for v in values)


def _describe_terms(terms: SearchTerms) -> str:
    parts = []
    if terms.interventions:
        parts.append(f"testing {' or '.join(terms.interventions)}")
    if terms.conditions:
        parts.append(f"for {' or '.join(terms.conditions)}")
    if terms.sponsors:
        parts.append(f"sponsored by {' or '.join(terms.sponsors)}")
    if terms.locations:
        parts.append(f"with sites in {' or '.join(terms.locations)}")
    if terms.keywords:
        parts.append(f"mentioning {' or '.join(terms.keywords)}")
    return " ".join(parts)


def describe(plan: SearchPlan) -> str:
    """Plain-English statement of exactly what was searched, built from the plan itself
    (not written by the agent, so it can never disagree with the actual search)."""
    if plan.is_comparison:
        sides = "; ".join(f"{g.label}: trials {_describe_terms(g)}" for g in plan.groups)
        text = f"Comparing {sides}"
    else:
        terms = _describe_terms(plan.groups[0])
        text = f"Trials {terms}" if terms else "All registered trials"

    filters = []
    if plan.study_types:
        filters.append(f"{_words(plan.study_types)} studies")
    if plan.phases:
        filters.append(_words(plan.phases))
    if plan.statuses:
        filters.append(_words(plan.statuses))
    if plan.intervention_types:
        filters.append(f"{_words(plan.intervention_types)} interventions")
    if plan.sponsor_classes:
        filters.append(f"{_words(plan.sponsor_classes)} lead sponsor")
    if plan.age_groups:
        filters.append(f"enrolling {_words(plan.age_groups)}")
    if plan.start_year and plan.end_year:
        filters.append(f"starting {plan.start_year}-{plan.end_year}")
    elif plan.start_year:
        filters.append(f"starting {plan.start_year} or later")
    elif plan.end_year:
        filters.append(f"starting {plan.end_year} or earlier")
    return text + (f" ({', '.join(filters)})" if filters else "") + "."


def filters_summary(plan: SearchPlan) -> dict:
    """What was actually searched, for meta.filters_applied (empty lists left out)."""
    summary = plan.model_dump(mode="json", exclude={"groups"}, exclude_none=True)
    summary["groups"] = [{k: v for k, v in g.model_dump().items() if v} for g in plan.groups]
    return summary
