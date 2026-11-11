"""find_trials and get_trial: listing trials and reading one, for questions that are not a chart.

    find_params(...)   the user's filters -> one GET /studies query string
    found(page, ...)   one page of results -> what the model reads (the true total, one row per trial)
    trial_detail(raw)  one record -> what the model reads (never the posted results)

Pure functions over raw API JSON; the tools in server.py do the HTTP call.
"""

import re
from collections import Counter
from typing import Any

from exploreclinicaltrials.fetch.models import build_advanced_filter
from exploreclinicaltrials.models.request import RecruitmentStatus, TrialPhase

STUDY_URL = "https://clinicaltrials.gov/study/{}"
DEFAULT_LIMIT = 20
MAX_LIMIT = 50
MAX_SITES = 20  # sites listed per trial by get_trial
MAX_MATCHING_SITES = 3  # sites listed per trial by find_trials
MAX_LISTED = 3  # conditions and interventions per trial in a list
MAX_SUMMARY = 1500
MAX_CRITERIA = 4000
MAX_ARM_TEXT = 300
MAX_OUTCOMES = 10
CUT = " …[cut; full text on the record page]"
SEXES = {"female": "FEMALE", "male": "MALE"}

FIND_FIELDS = [
    "NCTId", "BriefTitle", "OverallStatus", "Phase", "LeadSponsorName", "StartDate", "PrimaryCompletionDate",
    "Condition", "InterventionName", "EnrollmentCount", "MinimumAge", "MaximumAge", "Sex",
    "LocationFacility", "LocationCity", "LocationState", "LocationCountry", "LocationStatus",
]  # fmt: skip
DETAIL_FIELDS = (
    "protocolSection|hasResults"  # never resultsSection: outcomes and efficacy stay out
)
RESULTS_NOTE = (
    "Results are posted on the record page. This tool does not report them: it says nothing about "
    "efficacy or safety."
)
NCT_ID = re.compile(r"NCT\d{8}")


# --- The search ------------------------------------------------------------------------------


def nct_id(raw: str) -> str:
    """'nct05064059 ' -> 'NCT05064059'; anything else is refused."""
    value = raw.strip().upper()
    if not NCT_ID.fullmatch(value):
        raise ValueError(
            f"{raw!r} is not an NCT number (NCT followed by 8 digits, e.g. NCT05064059)."
        )
    return value


def age_filter(age: int) -> str:
    """Trials a person of this age may join. RANGE never matches a missing value, so a trial with no
    lower or upper age limit must be kept explicitly (most trials have no maximum age)."""
    return (
        f"(AREA[MinimumAge]RANGE[MIN, {age} years] OR AREA[MinimumAge]MISSING)"
        f" AND (AREA[MaximumAge]RANGE[{age} years, MAX] OR AREA[MaximumAge]MISSING)"
    )


def find_params(
    condition: str | None = None,
    intervention: str | None = None,
    terms: str | None = None,
    sponsor: str | None = None,
    location: str | None = None,
    recruitment_status: list[RecruitmentStatus] | None = None,
    trial_phase: list[TrialPhase] | None = None,
    age: int | None = None,
    sex: str | None = None,
    limit: int = DEFAULT_LIMIT,
    page_token: str | None = None,
) -> dict[str, str]:
    """The query string for one page of GET /studies. Raises ValueError on a bad input."""
    queries = {
        "query.cond": condition, "query.intr": intervention, "query.term": terms,
        "query.spons": sponsor, "query.locn": location,
    }  # fmt: skip
    params = {k: v.strip() for k, v in queries.items() if v and v.strip()}
    if not any(
        k in params for k in ("query.cond", "query.intr", "query.term", "query.spons")
    ):
        raise ValueError(
            "Give at least one of condition, intervention, terms or sponsor to search for."
        )
    if not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_LIMIT}.")
    advanced = []
    if phase := build_advanced_filter(trial_phase):
        advanced.append(phase)
    if age is not None:
        if not 0 <= age <= 120:
            raise ValueError("age must be a person's age in years, 0 to 120.")
        advanced.append(age_filter(age))
    if sex is not None:
        if sex.strip().lower() not in SEXES:
            raise ValueError(
                "sex must be 'female' or 'male' (trials open to all are always included)."
            )
        advanced.append(f"AREA[Sex]({SEXES[sex.strip().lower()]} OR ALL)")
    if recruitment_status:
        params["filter.overallStatus"] = ",".join(s.value for s in recruitment_status)
    if advanced:
        params["filter.advanced"] = " AND ".join(advanced)
    params |= {
        "fields": "|".join(FIND_FIELDS),
        "pageSize": str(limit),
        "countTotal": "true",
    }
    if page_token:
        params["pageToken"] = page_token
    return params


# --- Reading records ---------------------------------------------------------------------------


def _cut(text: str | None, limit: int) -> str | None:
    if not text:
        return None
    text = text.strip()
    return text if len(text) <= limit else text[:limit].rstrip() + CUT


def _unique(values) -> list[str]:
    return list(dict.fromkeys(v for v in values if v))


def _date(module: dict, key: str) -> str | None:
    return (module.get(key) or {}).get("date")


def _ages(eligibility: dict) -> str | None:
    low, high = eligibility.get("minimumAge"), eligibility.get("maximumAge")
    if low and high:
        return f"{low} to {high}"
    if low:
        return f"{low} and older"
    if high:
        return f"up to {high}"
    return None


def _site(location: dict) -> dict:
    keys = {
        "facility": "facility",
        "city": "city",
        "state": "state",
        "country": "country",
        "status": "status",
    }
    return {out: location[key] for out, key in keys.items() if location.get(key)}


def matching_sites(locations: list[dict], location: str | None) -> list[dict]:
    """Sites whose facility, city, state, zip or country contain every comma-separated part of
    `location` ('Portland, Maine' is not Portland, Oregon), recruiting sites first."""
    if not location:
        return []
    parts = [p.strip().lower() for p in location.split(",") if p.strip()]

    def text(site: dict) -> str:
        return " ".join(
            str(site.get(k, ""))
            for k in ("facility", "city", "state", "zip", "country")
        ).lower()

    hits = [_site(s) for s in locations if all(p in text(s) for p in parts)]
    return sorted(hits, key=lambda s: s.get("status") != "RECRUITING")


def _row(study: dict, location: str | None) -> dict:
    p = study.get("protocolSection", {})
    ident, status = p.get("identificationModule", {}), p.get("statusModule", {})
    design, eligibility = p.get("designModule", {}), p.get("eligibilityModule", {})
    locations = p.get("contactsLocationsModule", {}).get("locations", [])
    interventions = p.get("armsInterventionsModule", {}).get("interventions", [])
    row = {
        "nct_id": ident.get("nctId"),
        "url": STUDY_URL.format(ident.get("nctId")),
        "title": ident.get("briefTitle"),
        "status": status.get("overallStatus"),
        "phases": design.get("phases", []),
        "sponsor": p.get("sponsorCollaboratorsModule", {})
        .get("leadSponsor", {})
        .get("name"),
        "start": _date(status, "startDateStruct"),
        "primary_completion": _date(status, "primaryCompletionDateStruct"),
        "conditions": p.get("conditionsModule", {}).get("conditions", [])[:MAX_LISTED],
        "interventions": _unique(i.get("name") for i in interventions)[:MAX_LISTED],
        "enrollment": design.get("enrollmentInfo", {}).get("count"),
        "ages": _ages(eligibility),
        "sex": eligibility.get("sex"),
        "sites_total": len(locations),
    }
    if location:
        row["matching_sites"] = matching_sites(locations, location)[:MAX_MATCHING_SITES]
    return {k: v for k, v in row.items() if v not in (None, [], "")}


def found(page: dict, location: str | None, limit: int) -> dict[str, Any]:
    """One page of GET /studies as the model reads it."""
    trials = [_row(s, location) for s in page.get("studies", [])[:limit]]
    return {
        "total_matched": page.get("totalCount", len(trials)),
        "shown": len(trials),
        "next_page_token": page.get("nextPageToken"),
        "trials": trials,
    }


def trial_detail(record: dict, location: str | None = None) -> dict[str, Any]:
    """One record as the model reads it: registration, design, eligibility and sites, cut to size.
    The results section is never requested; `has_results` only says whether there is one."""
    p = record.get("protocolSection", {})
    ident, status = p.get("identificationModule", {}), p.get("statusModule", {})
    design, eligibility = p.get("designModule", {}), p.get("eligibilityModule", {})
    sponsors, arms = (
        p.get("sponsorCollaboratorsModule", {}),
        p.get("armsInterventionsModule", {}),
    )
    outcomes, contacts = (
        p.get("outcomesModule", {}),
        p.get("contactsLocationsModule", {}),
    )
    locations = contacts.get("locations", [])
    info = design.get("designInfo", {})
    sites = (
        matching_sites(locations, location)
        if location
        else [_site(s) for s in locations]
    )
    sites.sort(key=lambda s: s.get("status") != "RECRUITING")
    out = {
        "nct_id": ident.get("nctId"),
        "url": STUDY_URL.format(ident.get("nctId")),
        "title": ident.get("briefTitle"),
        "official_title": ident.get("officialTitle"),
        "acronym": ident.get("acronym"),
        "status": status.get("overallStatus"),
        "why_stopped": status.get("whyStopped"),
        "study_type": design.get("studyType"),
        "phases": design.get("phases", []),
        "enrollment": design.get("enrollmentInfo"),
        "dates": {
            "start": _date(status, "startDateStruct"),
            "primary_completion": _date(status, "primaryCompletionDateStruct"),
            "completion": _date(status, "completionDateStruct"),
            "last_update_posted": _date(status, "lastUpdatePostDateStruct"),
        },
        "sponsor": sponsors.get("leadSponsor"),
        "collaborators": [c.get("name") for c in sponsors.get("collaborators", [])],
        "conditions": p.get("conditionsModule", {}).get("conditions", []),
        "keywords": p.get("conditionsModule", {}).get("keywords", []),
        "summary": _cut(
            p.get("descriptionModule", {}).get("briefSummary"), MAX_SUMMARY
        ),
        "design": {
            k: info.get(k) for k in ("allocation", "primaryPurpose") if info.get(k)
        }
        | (
            {"masking": info["maskingInfo"].get("masking")}
            if info.get("maskingInfo")
            else {}
        ),
        "arms": [
            {
                "label": a.get("label"),
                "type": a.get("type"),
                "description": _cut(a.get("description"), MAX_ARM_TEXT),
                "interventions": a.get("interventionNames", []),
            }
            for a in arms.get("armGroups", [])
        ],
        "interventions": [
            {"type": i.get("type"), "name": i.get("name")}
            for i in arms.get("interventions", [])
        ],
        "primary_outcomes": [
            {"measure": o.get("measure"), "time_frame": o.get("timeFrame")}
            for o in outcomes.get("primaryOutcomes", [])
        ][:MAX_OUTCOMES],
        "secondary_outcomes": [
            o.get("measure") for o in outcomes.get("secondaryOutcomes", [])
        ][:MAX_OUTCOMES],
        "eligibility": {
            "sex": eligibility.get("sex"),
            "minimum_age": eligibility.get("minimumAge"),
            "maximum_age": eligibility.get("maximumAge"),
            "healthy_volunteers": eligibility.get("healthyVolunteers"),
            "criteria": _cut(eligibility.get("eligibilityCriteria"), MAX_CRITERIA),
        },
        "contacts": [
            {k: c[k] for k in ("name", "phone", "email") if c.get(k)}
            for c in contacts.get("centralContacts", [])
        ],
        "locations": {
            "total": len(locations),
            "by_country": dict(
                Counter(
                    s.get("country") for s in locations if s.get("country")
                ).most_common()
            ),
            **({"matching": len(sites)} if location else {}),
            "sites": sites[:MAX_SITES],
        },
        "has_results": bool(record.get("hasResults")),
    }
    if out["has_results"]:
        out["results_note"] = RESULTS_NOTE
    return _prune(out)


def _prune(value):
    """Drop empty values so the model reads only what the record has."""
    if isinstance(value, dict):
        pruned = {k: _prune(v) for k, v in value.items()}
        return {
            k: v
            for k, v in pruned.items()
            if v not in (None, [], {}, "") or k == "has_results"
        }
    if isinstance(value, list):
        return [_prune(v) for v in value]
    return value
