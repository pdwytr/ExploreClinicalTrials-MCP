"""Deterministic glue between steps: adding the user's structured filters to the
planner's searches, and summarising what was searched. No AI here."""

import logging

from cheiron.fetch.models import StudySearchParams, build_advanced_filter
from cheiron.models.request import QueryRequest
from cheiron.workflow.plans import SearchPlan

log = logging.getLogger(__name__)

# Request field -> API text parameter
_TEXT_FILTERS = {"drug_name": "query.intr", "condition": "query.cond", "sponsor": "query.spons", "country": "query.locn"}

PreparedSearch = tuple[str, StudySearchParams]  # (label, request ready to execute)


def phrase(text: str) -> str:
    """Quote a user value so the API matches it as a phrase and never reads it as syntax.

    Unquoted, 'multiple sclerosis' also matches 'tuberous sclerosis' (68 vs 55
    trials in a live check). Inner double quotes are dropped: they would end the phrase.
    """
    return '"' + text.replace('"', "").strip() + '"'


def _and(existing: str | None, addition: str) -> str:
    return f"({existing}) AND {addition}" if existing else addition


def apply_request_filters(plan: SearchPlan, request: QueryRequest) -> tuple[list[PreparedSearch], list[str]]:
    """Add every structured field the user sent to every search, so filters are guaranteed.

    - Text fields (drug, condition, sponsor, country) are AND-ed onto the matching
      parameter, unless the planner's value already contains them.
    - Phases and years are AND-ed onto filter.advanced.
    - Statuses replace filter.overallStatus (the user's explicit choice wins).
    Exception: if the searches compare sides on that very parameter (e.g. two drugs),
    AND-ing the user's value onto both would change the comparison, so it is skipped
    with a user-facing warning.

    Returns the executable searches and warnings.
    """
    warnings: list[str] = []
    all_params = [dict(s.params) for s in plan.searches]

    for req_field, api_param in _TEXT_FILTERS.items():
        wanted = getattr(request, req_field)
        if wanted is None:
            continue
        values = {p.get(api_param, "").casefold() for p in all_params}
        if plan.is_comparison and len(values) > 1:
            warnings.append(f"Ignored {req_field}={wanted!r}: the question compares searches by {api_param}.")
            continue
        for p in all_params:
            if wanted.casefold() not in p.get(api_param, "").casefold():
                log.info("added user filter: %s += %r", api_param, wanted)
                p[api_param] = _and(p.get(api_param), phrase(wanted))

    advanced = build_advanced_filter(request.trial_phase, request.start_year, request.end_year)
    statuses = "|".join(s.value for s in request.recruitment_status) if request.recruitment_status else None
    for p in all_params:
        if advanced and advanced not in p.get("filter.advanced", ""):
            p["filter.advanced"] = _and(p.get("filter.advanced"), advanced)
        if statuses and p.get("filter.overallStatus") != statuses:
            log.info("user status filter replaces %r", p.get("filter.overallStatus"))
            p["filter.overallStatus"] = statuses

    prepared = [(s.label, StudySearchParams(search=p)) for s, p in zip(plan.searches, all_params)]
    return prepared, warnings


def filters_summary(prepared: list[PreparedSearch]) -> dict:
    """The exact API searches that ran, for meta.filters_applied (rerunnable as-is)."""
    return {"searches": [{"label": label, "params": params.search} for label, params in prepared]}
